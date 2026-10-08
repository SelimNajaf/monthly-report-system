"""Persistent parse cache — memoize the .docx parse across runs.

Why this exists
---------------
``main.py`` re-parses **every** ``.docx`` under ``input/`` on every run, then filters
by target month afterwards (see :func:`document_aggregator.build_monthly_report`).
Parsing is CPU-bound lxml, so a corpus that grows one month at a time makes each run
cost O(total history) rather than O(new files). Month 12 re-parses eleven months of
reports to emit one.

The files cannot simply be archived away: cross-month retest linking
(:func:`retest_tracker.pull_cross_month_parents`) reads earlier months' parents from
the in-memory parse cache. So the fix memoizes the *work*, not the files — every
historical report stays on disk and reachable, but is parsed only once.

The pattern
-----------
A content-addressed store on disk: one JSON entry per file, named by the SHA-256 of
the file's **bytes**. Keying on content, not path or mtime, buys three properties for
free:

* STAGE-0 sorting (:func:`pre_processor.sort_input_files`) moves a ``.docx`` between
  folders — a path/mtime key would miss after every sort; a content key does not.
* Byte-identical twins (``…_en.docx`` / ``…_en_en.docx``) share one entry — the same
  dedup the aggregator does downstream, paid once here too.
* An edit changes the bytes, so it changes the hash, so it re-parses. No touch-without-
  edit false miss, no edit-preserving-mtime false hit — the same integrity argument as
  :mod:`upload_ledger`.

Contract parity
---------------
:func:`read_many_cached` returns exactly what :func:`docx_reader.read_many` returns —
``(cache, errors, textless)`` — so it is a drop-in swap at the one call site.

What is and is not cached
-------------------------
Only *clean parses* are stored, including textless files (their ``has_text=False`` is
recorded, so the "scanned image" boundary check still fires from the cache). Parse
**errors are never cached**: a locked or momentarily-unreadable file is transient and
must be retried next run, exactly as an uncached run would.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from . import docx_reader
from .console import progress_printer

#: Bumped whenever an entry's shape **or meaning** changes. A stale-schema entry is
#: treated as a miss and re-parsed rather than misread — the same discipline as the
#: upload ledger's SCHEMA_VERSION and the probe's PROBE_SCHEMA.
#:
#: 2 (ADR-003): the payload shape is untouched, but a PDF's tables now come from the
#: original PDF instead of a pdf2docx conversion of it. Same `list[table][row][cell]`,
#: different content — an entry written under schema 1 for a PDF holds the shattered
#: grid that produced the wrong verdicts, so every entry must be rebuilt. Content
#: addressing alone would not catch this: the file bytes never changed, the reader did.
CACHE_SCHEMA = 2

#: Default store location, relative to the project root. Machine-local, gitignored.
DEFAULT_CACHE_DIRNAME = ".parse_cache"

_HASH_CHUNK = 1 << 20  # 1 MiB — same streaming block as upload_ledger / pre_processor


def content_hash(path: str | Path) -> str | None:
    """Streaming SHA-256 of a file's bytes, or ``None`` if it cannot be read.

    Never raises — a locked/vanished file returns ``None`` so the caller treats it as
    a miss and lets the real parser report the error (which is then not cached). Streams
    in 1 MiB blocks so a 300 MB scanned-image ``.docx`` never loads whole into memory.
    Mirrors :func:`pre_processor._sha256`.
    """
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(_HASH_CHUNK), b""):
                h.update(block)
    except OSError:
        return None
    return h.hexdigest()


class ParseCache:
    """A content-addressed store of parsed ``.docx`` tables.

    One JSON file per hash under ``<dir>/<sha256>.json`` — per-entry files give atomic
    writes and never rewrite a monolith, so two concurrent runs cannot corrupt each
    other's store. A missing directory is a cold cache, not an error.
    """

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)

    def _entry_path(self, digest: str) -> Path:
        return self.dir / f"{digest}.json"

    def get(self, digest: str) -> tuple[list, bool] | None:
        """Return ``(tables, has_text)`` for ``digest``, or ``None`` on a miss.

        A miss is any of: no entry file, an unreadable/corrupt entry, or an entry
        written under a different :data:`CACHE_SCHEMA`. All three re-parse rather than
        risk handing back wrong or malformed tables.
        """
        entry = self._entry_path(digest)
        if not entry.is_file():
            return None
        try:
            data = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("schema") != CACHE_SCHEMA:
            return None
        tables = data.get("tables")
        if not isinstance(tables, list):
            return None
        return tables, bool(data.get("has_text", True))

    def put(self, digest: str, tables: list, has_text: bool) -> None:
        """Store one clean parse, atomically. Best-effort — never fatal.

        A store that cannot be written (full disk, permissions) must not lose the
        parse that just succeeded: the run continues uncached for that file, and the
        next run retries the write. Uses the temp-file + ``os.replace`` dance from
        :meth:`UploadLedger._flush` so a crash mid-write leaves no truncated entry.
        """
        payload = {"schema": CACHE_SCHEMA, "has_text": has_text, "tables": tables}
        text = json.dumps(payload, ensure_ascii=False) + "\n"
        tmp_name = None
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", dir=str(self.dir),
                    prefix=f"{digest}.", suffix=".tmp", delete=False) as tmp:
                tmp_name = tmp.name
                tmp.write(text)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, self._entry_path(digest))
            tmp_name = None
        except OSError:
            pass
        finally:
            if tmp_name is not None and os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass

    def gc(self, live_digests: set[str]) -> int:
        """Delete entries whose hash was not referenced this run. Returns the count.

        Safe because every ``.docx`` still on disk — including cross-month retest
        parents left in ``input/`` — is hashed on every run and so is in
        ``live_digests``. Only entries for files that were genuinely removed go stale.
        Never fatal: a locked entry is left for the next run. Callers gate this behind
        the run's housekeeping flag (``--no-clean`` skips it), matching the rest of the
        pipeline's recoverable-cleanup posture.
        """
        if not self.dir.is_dir():
            return 0
        removed = 0
        for entry in self.dir.glob("*.json"):
            if entry.stem in live_digests:
                continue
            try:
                entry.unlink()
                removed += 1
            except OSError:
                pass
        return removed


def read_many_cached(paths, cache_dir: str | Path = DEFAULT_CACHE_DIRNAME,
                     max_workers: int | None = None, progress_every: int = 0):
    """Parse many ``.docx``, reusing a persistent parse cache. Drop-in for read_many.

    Returns ``(cache, errors, textless)`` — the exact contract of
    :func:`docx_reader.read_many`, plus a fourth stat channel on the returned tuple's
    peers is deliberately NOT added, so the call site stays a one-line swap. Hit/miss
    counts are exposed via :attr:`read_many_cached.last_stats` for the caller to log.

    Hits are served from disk with no parse. Misses are delegated to
    :func:`docx_reader.read_many` in one batch, so the process pool and its serial
    fallback are reused untouched, then each freshly-parsed clean file is stored.

    ``progress_every`` turns on the live ``[Stage 1: Parsing] [i/N]`` counter for
    the hash-and-lookup walk below, and is forwarded to the delegated parse. The
    two passes count separately on purpose: this one covers every file, the parse
    only the misses, and a single denominator would show a counter that sprints
    through the hits and then appears to stall.

    A PDF whose two readers disagree on a blocking field (ADR-003) is **never
    stored**. Storing it would make the disagreement a one-run event: the file is
    quarantined, an operator returns it unchanged, and the second run serves the
    cached tables, sees no disagreement and compiles the very verdict the
    cross-check refused to guess at. Re-parsing those few files every run costs
    milliseconds; caching them would cost the guarantee.
    """
    paths = [Path(p) for p in paths]
    store = ParseCache(cache_dir)

    cache: dict[Path, list] = {}
    errors: dict[Path, str] = {}
    textless: list[Path] = []
    live_digests: set[str] = set()

    misses: list[Path] = []
    miss_digest: dict[Path, str] = {}
    hits = 0

    emit = progress_printer(docx_reader.STAGE_PARSE, len(paths), progress_every)

    for index, path in enumerate(paths, 1):
        emit(index, "Processing parse_cache...")
        digest = content_hash(path)
        if digest is None:
            # Cannot hash (locked/vanished) — let the real reader report it; the error
            # is not cached. Do not add to live_digests, so a file that vanished mid-run
            # does not protect its stale entry from GC.
            misses.append(path)
            continue
        live_digests.add(digest)
        entry = store.get(digest)
        if entry is None:
            misses.append(path)
            miss_digest[path] = digest
            continue
        tables, has_text = entry
        cache[path] = tables
        if not has_text:
            textless.append(path)
        hits += 1

    disagreements: list = []
    if misses:
        m_cache, m_errors, m_textless = docx_reader.read_many(
            misses, max_workers=max_workers, progress_every=progress_every)
        textless_set = set(m_textless)
        disagreements = list(docx_reader.read_many.last_disagreements)
        blocked = {Path(d.path) for d in disagreements if d.blocking}
        for path, tables in m_cache.items():
            cache[path] = tables
            has_text = path not in textless_set
            if not has_text:
                textless.append(path)
            # Store only clean parses. A file with no hash (miss_digest miss) is skipped
            # — it had no key to store under. A blocking disagreement is not stored
            # either; see the docstring.
            digest = miss_digest.get(path)
            if digest is not None and path not in blocked:
                store.put(digest, tables, has_text)
        errors.update(m_errors)   # errors are never cached — transient, must retry
    read_many_cached.last_disagreements = disagreements

    read_many_cached.last_stats = {
        "hits": hits,
        "misses": len(misses),
        # The miss PATHS, not just the count: a file parsed fresh is one whose bytes
        # are new or changed since the last run, which is exactly the "what moved?"
        # signal the incremental compile skip in main.py needs. Published here rather
        # than returned so the call site stays the one-line read_many swap.
        "miss_paths": list(misses),
        "total": len(paths),
        "live_digests": live_digests,
        "store": store,
    }
    return cache, errors, textless


#: Populated by the most recent :func:`read_many_cached` call so the caller can log the
#: hit/miss split and run GC against the same store without re-deriving either.
read_many_cached.last_stats = {}

#: The PDF cross-check disagreements the most recent call turned up (ADR-003),
#: forwarded from ``docx_reader.read_many`` so main.py reads one place regardless of
#: which of the two entry points it called. Cache hits contribute none — a hit means
#: those bytes already passed the cross-check.
read_many_cached.last_disagreements = []
