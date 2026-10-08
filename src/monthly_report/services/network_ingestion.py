"""STAGE 0-LAN — read-only ingestion of fresh reports off the LAN network share.

Before the local pipeline runs, :func:`sync_from_lan` discovers reports on the
SMB share configured in ``network_ingestion.lan_sources`` and copies the NEW ones
into ``input/UnSorted/``, where the existing STAGE -1/0 (convert + sort) drains
them. Nothing new needs sorting logic — a staged file rides the current path.

STRICTLY READ-ONLY on the share: the only network operations are ``os.scandir``,
``entry.stat()`` and reading bytes for the copy. No file or folder on the share is
ever moved, renamed, edited or deleted — every write lands under the local
``input/`` tree.

SCOPED BY YEAR, not month. Share filenames carry a 2-digit year (``U-UT-26-001``)
and year-bearing folders (``DP-2026``, ``2026``) but no month token — the true
inspection month lives inside each ``.docx``. So the sync descends only into the
target year's folders (pruning ``DP-2025`` / ``2019`` / ...) and copies every new
file there; the existing :func:`pre_processor.discover_groups` still compiles ONLY
the requested month, so over-copying the year is harmless and, by design, lets the
local history accumulate for cross-month retest linking.

GRACEFUL OFFLINE: each root is probed under a bounded timeout (the same daemon
probe the discovery scanner uses). An unreachable / timed-out root is skipped with
a warning; if the whole share is down the caller prints the fallback notice and the
run proceeds on whatever is already in ``input/``. The sync never raises.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# The reusable share primitives live in the standalone discovery scanner at the
# repo root (proven-importable: its own tests do ``import discover_network_share``).
# Add the repo root so this package module resolves it regardless of caller CWD.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from discover_network_share import (  # noqa: E402
    DEFAULT_ROOT_TIMEOUT_S, _YEAR_RE, _reachable_within, filename_date,
    is_utility_folder, is_valid_report_filename, is_year_folder, normalize_unc,
    report_serial)

from ..date_detector import parse_inspection_date  # noqa: E402
from ..docx_reader import read_tables  # noqa: E402
from ..extractor import extract_meta  # noqa: E402
from ..naming import UNSORTED_DIR  # noqa: E402
from ..parse_cache import content_hash  # noqa: E402
from ..pre_processor import SETTLED_DIRS  # noqa: E402
from ..report_identity import report_key_of  # noqa: E402
from .ingestion_registry import (DEFAULT_REGISTRY_REL,  # noqa: E402
                                 SCHEMA_VERSION, IngestionRegistry,
                                 read_manifest, write_manifest)

#: Report extensions the sync stages; everything else on the share is ignored.
#: Legacy ``.doc`` is NOT here — ``docx_reader.read_tables`` cannot open it, so
#: staging one would only produce a quarantine entry. Such files are reported by
#: the walk (see :func:`_iter_share_files`) for manual conversion instead.
STAGE_EXTS = (".docx", ".pdf")

#: A share folder with this name (case-insensitive) holds reports the inspectors
#: set aside for deletion. Nothing under it is ever staged (R3-B, operator
#: decision 2026-10-05), whatever ``stage_size_mismatch`` says.
DELETE_FOLDER = "delete"

#: The no-clobber tail :func:`_nonclobber_dest` appends (``-lan``, ``-lan2`` ...).
_LAN_TAIL = re.compile(r"-lan\d*$", re.IGNORECASE)


def stage_size_mismatch(settings) -> bool:
    """``network_ingestion.stage_size_mismatch`` (default ``False``).

    ``True``: a share file never transferred because a local file has the same
    NAME is staged as a ``-lan`` twin when its size differs from every local copy
    of that name. The existing hash dedup and twin logic then decide.
    """
    block = (getattr(settings, "raw", None) or {}).get("network_ingestion") or {}
    return block.get("stage_size_mismatch", False) is True


def under_delete_folder(path) -> bool:
    """True when any folder segment of ``path`` is named ``delete`` (any case)."""
    parts = re.split(r"[\\/]", str(path))[:-1]
    return any(part.casefold() == DELETE_FOLDER for part in parts)


def _stream(message: str) -> None:
    """Write one progress line straight to stdout, unbuffered.

    The share walk takes minutes; a block-buffered stdout (which is what Python
    gives a redirected/piped run) would hold every line until the run ends and
    make the sync look frozen. Writing + flushing per line keeps the operator's
    terminal live.
    """
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


@dataclass
class LanSyncResult:
    """Outcome of one STAGE 0-LAN sync — everything ``main.py`` needs to log."""

    staged: list[str] = field(default_factory=list)     # filenames copied in
    modified: list[str] = field(default_factory=list)   # changed on share, re-copied
    skipped_dupes: int = 0                               # already present locally
    checked: int = 0                                     # candidates inspected
    unchanged: int = 0                                   # O(1) registry skips
    elapsed_s: float = 0.0                               # wall time of the compare loop
    roots_scanned: int = 0
    roots_reachable: int = 0
    roots_offline: int = 0
    offline_paths: list[str] = field(default_factory=list)
    bytes_copied: int = 0
    share_label: str = ""                                # e.g. \\<host>\<share>

    @property
    def staged_count(self) -> int:
        return len(self.staged)

    @property
    def modified_count(self) -> int:
        return len(self.modified)

    @property
    def unreachable_all(self) -> bool:
        """True when roots were configured but none could be reached (share down)."""
        return self.roots_scanned > 0 and self.roots_reachable == 0


def _target_year(target_month: str) -> str:
    """``"2026-08"`` -> ``"2026"``. Falls back to the leading 4 digits.

    ``target_month`` is already canonical ``YYYY-MM`` (main.py normalises the CLI
    flag before the sync). Kept defensive so a stray value never raises here — an
    unparseable month yields ``""`` and the walk then prunes nothing by year.
    """
    text = str(target_month or "").strip()
    head = text.split("-", 1)[0]
    return head if len(head) == 4 and head.isdigit() else ""


def _share_label(normalized: str) -> str:
    """``\\\\host\\share\\Method`` -> ``\\\\host\\share`` for a compact log line.

    Non-UNC (local test) paths are returned unchanged.
    """
    if normalized.startswith("\\\\"):
        parts = normalized.split("\\")          # ['', '', host, share, method, ...]
        if len(parts) >= 4:
            return "\\\\" + "\\".join(parts[2:4])
    return normalized


def _host_of(normalized: str) -> str | None:
    """Extract the host from a normalised UNC (``\\\\host\\share\\...`` -> ``host``).

    ``None`` for a non-UNC (local) path — used only to short-circuit repeated
    probes of the SAME dead host (all 8 configured roots share one host), so a
    fully offline share costs one timeout, not eight.
    """
    if normalized.startswith("\\\\"):
        parts = normalized.split("\\")          # ['', '', host, share, ...]
        if len(parts) >= 3 and parts[2]:
            return parts[2].casefold()
    return None


def _local_index(settings) -> tuple[set[str], set[str]]:
    """Build the dedup indexes from local state (no network).

    Returns ``(stems, digests)``:

    * ``stems`` — case-folded filename stems of every ``.docx``/``.pdf`` anywhere
      under ``input/`` (working dirs, ``PDF_ARCHIVE/``, ``_PRUNED/``,
      ``SKIPPED_REPORTS/``, ``UnSorted/``). A share file whose stem is already here
      is skipped BEFORE any bytes transfer.
    * ``digests`` — SHA-256 content hashes already known: the ``.parse_cache/``
      entry filenames are ``<sha256>.json`` (a ready-made content index), so a
      differently-named but byte-identical report is caught after a local copy.
    """
    stems: set[str] = set()
    input_dir = Path(settings.input_dir)
    if input_dir.is_dir():
        for p in input_dir.rglob("*"):
            if p.suffix.casefold() in STAGE_EXTS and not p.name.startswith("~$"):
                stems.add(p.stem.casefold())

    digests: set[str] = set()
    perf = settings.raw.get("performance", {}) or {}
    cache_dir = Path(settings.project_root) / str(
        perf.get("parse_cache_dir", ".parse_cache"))
    if cache_dir.is_dir():
        for entry in cache_dir.glob("*.json"):
            digests.add(entry.stem.casefold())
    return stems, digests


def _prune_year_folder(name: str, target_year: str, min_year: int | None) -> bool:
    """True when a year-named subfolder is out of scope and should be pruned.

    Two scoping modes, mutually exclusive:

    * ``min_year`` set (cutoff engine) — prune a year-folder only when EVERY 4-digit
      token it carries is ``< min_year`` (so ``…-2024``/``2019`` go, ``…-2025``/
      ``2026`` stay). This keeps the cutoff month's own year and everything after.
    * ``target_year`` set (single-month engine) — prune a year-folder that carries
      no token equal to the target year.

    A non-year folder, or a year-folder with no parseable token, is never pruned.
    """
    if not is_year_folder(name):
        return False
    tokens = _YEAR_RE.findall(name)
    if not tokens:
        return False
    if min_year is not None:
        return all(int(tok) < min_year for tok in tokens)
    return bool(target_year) and target_year not in tokens


def _iter_share_files(root: Path, target_year: str, log, *,
                      min_year: int | None = None, settings=None,
                      stats: dict | None = None):
    """Yield stageable report files under ``root`` in scope, read-only.

    Explicit ``os.scandir`` stack (same cached-stat traversal as the discovery
    scanner). A subfolder is PRUNED when :func:`_prune_year_folder` puts it out of
    year scope or when :func:`is_utility_folder` marks it administrative
    (``Templates/``, ``Archive/``, ``Certificates/``); a non-year folder or an
    in-scope year-folder is always descended, so a file that sits outside a
    year-named folder is never missed. Never raises on a mid-walk ``OSError`` — an
    unreadable subtree is skipped and the walk continues.

    When ``settings`` is given every filename must additionally pass
    :func:`is_valid_report_filename` — junk, ``~$`` Word lock files, admin
    documents and unregistered-client names are dropped before any transfer. A
    legacy ``.doc`` that IS a valid report name is reported once and not yielded
    (the parser cannot open it).
    """
    stack: list[Path] = [root]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                entries = list(it)
        except OSError as exc:
            log(f"[LAN Sync] skipped unreadable folder {cur} ({type(exc).__name__}).")
            continue
        for entry in entries:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            if is_dir:
                if _prune_year_folder(entry.name, target_year, min_year):
                    continue                    # out-of-scope year-folder — prune
                if entry.name.casefold() == DELETE_FOLDER:
                    continue                    # set aside for deletion — never staged
                if is_utility_folder(entry.name):
                    continue                    # templates / archive / forms — prune
                stack.append(Path(entry.path))
                continue
            if settings is not None and not is_valid_report_filename(entry.name,
                                                                     settings):
                if stats is not None:
                    stats["rejected"] = stats.get("rejected", 0) + 1
                continue                        # junk / admin / unregistered client
            suffix = Path(entry.name).suffix.casefold()
            if suffix == ".doc":
                log(f"[LAN Sync] legacy .doc not stageable: {entry.name} "
                    "(convert to .docx by hand).")
                continue
            if suffix in STAGE_EXTS:
                yield entry


def _nonclobber_dest(dest_dir: Path, name: str) -> Path:
    """A destination path under ``dest_dir`` that does not overwrite an existing file.

    Preserves the original name when free; otherwise inserts ``-lan`` (then
    ``-lan2``, ``-lan3`` ...) before the suffix. Copy-not-clobber keeps a
    same-named but genuinely different report from being lost.
    """
    dest = dest_dir / name
    if not dest.exists():
        return dest
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 1
    while True:
        tag = "-lan" if n == 1 else f"-lan{n}"
        candidate = dest_dir / f"{stem}{tag}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def _lan_twin_dest(dest_dir: Path, name: str, taken: set) -> Path:
    """``-lan`` / ``-lanN`` destination for a same-name, different-size share file.

    Always a twin name, never ``name`` itself: the local copy may sit in a sorted
    folder rather than ``dest_dir``, and the twin must not collide with it when
    the sort moves it there. A tail already used anywhere under ``input/``
    (``taken``: case-folded local file names) is skipped.
    """
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 1
    while True:
        tag = "-lan" if n == 1 else f"-lan{n}"
        candidate = dest_dir / f"{stem}{tag}{suffix}"
        if not candidate.exists() and candidate.name.casefold() not in taken:
            return candidate
        n += 1


def _entry_metadata(entry) -> tuple[int, float] | None:
    """``(size, mtime)`` for one share entry, or ``None`` when it cannot be stat'd.

    On Windows ``os.scandir`` carries size and timestamps in the directory listing
    itself, so ``DirEntry.stat()`` is served from that cached result — no extra SMB
    round-trip. This is what makes the registry compare free.
    """
    try:
        info = entry.stat(follow_symlinks=False)
    except OSError:
        return None
    return info.st_size, info.st_mtime


def _registry_path(settings, override=None) -> Path:
    """Where the ingestion manifest lives — ``<project_root>/.state/…`` by default."""
    if override is not None:
        return Path(override)
    return Path(settings.project_root) / DEFAULT_REGISTRY_REL


def _stem_twins(settings, name: str) -> tuple[list[Path], list[Path]]:
    """Local copies that share ``name``'s stem, split into ``(live, settled)``.

    ONE matching rule for the whole module: same case-folded stem, a
    :data:`STAGE_EXTS` suffix, no ``~$`` Word lock file. ``live`` is the working
    tree; ``settled`` is everything already parked under :data:`SETTLED_DIRS`
    (``PDF_ARCHIVE/``, ``SKIPPED_REPORTS/``, ``_PRUNED/``). A settled copy is never
    overwritten, but it still proves the content is already here — which is what the
    modified-file dedup needs and :func:`_replace_target` deliberately ignores.
    """
    live: list[Path] = []
    settled: list[Path] = []
    input_dir = Path(settings.input_dir)
    if not input_dir.is_dir():
        return live, settled
    stem_cf = Path(name).stem.casefold()
    for p in input_dir.rglob("*"):
        if (p.suffix.casefold() not in STAGE_EXTS
                or p.name.startswith("~$")
                or p.stem.casefold() != stem_cf):
            continue
        if p.relative_to(input_dir).parts[0].casefold() in SETTLED_DIRS:
            settled.append(p)
        else:
            live.append(p)
    return live, settled


def _name_sizes(settings) -> tuple[dict[str, list[int]], set[str]]:
    """``({case-folded file name: [sizes]}, {case-folded file names})`` of every
    local report copy under ``input/``.

    A ``-lan`` / ``-lanN`` twin answers to its base name in the size map, so a
    share file whose bytes were already staged as a twin is matched by size too.
    The name set is the literal names, for picking a free twin tail.
    """
    sizes: dict[str, list[int]] = {}
    names: set[str] = set()
    input_dir = Path(settings.input_dir)
    if not input_dir.is_dir():
        return sizes, names
    for p in input_dir.rglob("*"):
        if p.suffix.casefold() not in STAGE_EXTS or p.name.startswith("~$"):
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        base = _LAN_TAIL.sub("", p.stem) + p.suffix
        sizes.setdefault(base.casefold(), []).append(size)
        names.add(p.name.casefold())
    return sizes, names


def _size_differs(name_sizes: dict, name: str, size: int) -> bool:
    """True when local copies named ``name`` exist and NONE has ``size`` bytes.

    No local copy of that exact name (only a twin of another kind, ``.docx`` vs
    ``.pdf``) is not a size mismatch: that file is skipped as before.
    """
    local = name_sizes.get(name.casefold())
    return bool(local) and size not in local


def _live_twins(settings, name: str) -> list[Path]:
    """Every live (non-settled) local copy of ``name`` — see :func:`_stem_twins`."""
    return _stem_twins(settings, name)[0]


def _same_suffix(paths: list[Path], name: str) -> list[Path]:
    """The members of ``paths`` that carry ``name``'s own suffix (case-folded).

    Stem twins are the right net for DEDUP — a ``.pdf`` whose bytes already sit
    anywhere locally is not new — but the wrong one for REPLACE: a refreshed share
    ``U-UT-26-008.pdf`` once overwrote the live ``U-UT-26-008.docx`` with PDF bytes,
    leaving a ``.docx`` the parser could only quarantine as unreadable. A file is
    only ever replaced by a newer copy of the same kind.
    """
    suffix = Path(name).suffix.casefold()
    return [p for p in paths if p.suffix.casefold() == suffix]


def _duplicate_twin(digest: str, twins: list[Path], dest: Path) -> Path | None:
    """The first twin in ``twins`` whose bytes hash to ``digest``, else ``None``.

    ``dest`` (the copy just written) is skipped so a file never matches itself. An
    unreadable twin hashes to ``None`` and simply does not match.
    """
    wanted = digest.casefold()
    for path in twins:
        if path == dest:
            continue
        other = content_hash(path)
        if other is not None and other.casefold() == wanted:
            return path
    return None


def _replace_target(settings, name: str) -> Path | None:
    """The one local copy of ``name`` that a modified share file should overwrite.

    Returns the path only when EXACTLY one live copy with the SAME suffix exists
    under ``input/`` (a stem twin of another kind is never a target; the
    settled trees — ``PDF_ARCHIVE/``, ``SKIPPED_REPORTS/``, ``_PRUNED/`` — are not
    live and never overwritten). Zero matches means the file was never staged where
    we can find it, two or more means we cannot tell which is authoritative; both
    cases fall back to the non-clobbering ``-lan`` twin so nothing is destroyed on a
    guess.
    """
    matches = _same_suffix(_live_twins(settings, name), name)
    return matches[0] if len(matches) == 1 else None


def _collect_candidates(settings, result, lan_sources, timeout, log, *,
                        target_year: str = "", min_year: int | None = None,
                        stats: dict | None = None):
    """Phase A — probe every root and gather the in-scope entries into one list.

    Materialising the candidates BEFORE any copy is what makes the ``i/N`` progress
    counter possible (``N`` is unknown while the walk is still a generator) and lets
    twin preference see ``.docx`` files that live under a different root than their
    ``.pdf``. Reachability accounting is written into ``result``; a host already
    proven dead this run is not re-probed.
    """
    entries: list = []
    dead_hosts: set[str] = set()
    for raw in lan_sources:
        normalized = normalize_unc(raw)
        result.roots_scanned += 1
        root = Path(normalized)
        host = _host_of(normalized)

        # A host already proven dead this run is offline without re-probing — all
        # configured roots share one host, so a down share costs one timeout total.
        if host is not None and host in dead_hosts:
            result.roots_offline += 1
            result.offline_paths.append(normalized)
            continue

        reachable = _reachable_within(root, timeout) if (timeout and timeout > 0) \
            else (root.exists() and root.is_dir())
        if not reachable:
            result.roots_offline += 1
            result.offline_paths.append(normalized)
            if host is not None:
                dead_hosts.add(host)
            log(f"[LAN Sync] {normalized} unreachable — skipping.")
            continue

        result.roots_reachable += 1
        log(f"[LAN Sync] Scanning {normalized} ...")
        entries.extend(_iter_share_files(root, target_year, log,
                                         min_year=min_year, settings=settings,
                                         stats=stats))
    return entries


def sync_from_lan(settings, target_month: str, *,
                  timeout: float | None = DEFAULT_ROOT_TIMEOUT_S,
                  registry_path=None, log=_stream) -> LanSyncResult:
    """Copy new/changed target-year reports off the LAN share into ``input/UnSorted/``.

    Read-only on the share, idempotent across runs, and never raising: an offline
    share yields an empty result with ``unreachable_all`` set, not an exception.
    Returns a :class:`LanSyncResult` for the caller to log.

    Each candidate is classified against the persistent ingestion registry
    (:mod:`ingestion_registry`) using the ``(size, mtime)`` the directory walk
    already carries:

    * **UNCHANGED** — fingerprint matches. Skipped in O(1): no filename scan, no
      hash, not one byte off the network. This is the common case on a monthly
      re-run, and the whole point of the registry.
    * **MODIFIED** — recorded before, but size or mtime moved. The report was edited
      on the share, so the local copy is stale; it is re-copied OVER the single live
      local copy (:func:`_replace_target`), or staged as a ``-lan`` twin when that
      copy cannot be identified unambiguously.
    * **ABSENT** — never ingested. The original path: local-filename skip, else copy
      then content-hash dedup.

    Every classified file is fingerprinted before returning, including the ones
    skipped without transfer — so a first run over an already-populated ``input/``
    costs one full walk and every run after it is O(new + changed).
    """
    result = LanSyncResult()
    lan_sources = (settings.raw.get("network_ingestion") or {}).get("lan_sources") or []
    if not lan_sources:
        return result                            # feature not configured — no-op

    target_year = _target_year(target_month)
    result.share_label = _share_label(normalize_unc(lan_sources[0]))
    registry = IngestionRegistry.load(_registry_path(settings, registry_path))
    unsorted_dir = Path(settings.input_dir) / UNSORTED_DIR

    entries = _collect_candidates(settings, result, lan_sources, timeout, log,
                                  target_year=target_year)
    total = len(entries)

    # The local index is what the ABSENT branch dedups against, and building it walks
    # the whole input/ tree. Deferred until a candidate actually needs it, so a run
    # where the registry answers for every file never pays for it.
    index_cache: list | None = None

    def _indexes():
        nonlocal index_cache
        if index_cache is None:
            index_cache = list(_local_index(settings))
        return index_cache

    # network_ingestion.stage_size_mismatch — off: this map is never built.
    size_mismatch = stage_size_mismatch(settings)
    sizes_cache: tuple | None = None

    def _sizes():
        nonlocal sizes_cache
        if sizes_cache is None:
            sizes_cache = _name_sizes(settings)
        return sizes_cache

    t0 = time.perf_counter()
    for index, entry in enumerate(entries, 1):
        tag = f"[LAN Sync {index}/{total}]"
        result.checked += 1
        meta = _entry_metadata(entry)
        known = registry.get(entry.path)
        if under_delete_folder(entry.path):
            continue                             # set aside on the share — never staged
        # A file never transferred (no hash) because a same-NAME local file exists,
        # whose size differs from every local copy of that name: staged as a -lan
        # twin below, even though the registry would call it unchanged.
        size_twin = (size_mismatch and meta is not None
                     and (known is None or known.sha256 is None)
                     and _size_differs(_sizes()[0], entry.name, meta[0]))

        # --- UNCHANGED: the O(1) skip -------------------------------------------
        if (meta is not None and registry.is_unchanged(entry.path, *meta)
                and not size_twin):
            result.unchanged += 1
            continue

        # --- MODIFIED: recorded before, but the bytes moved ----------------------
        if known is not None and not size_twin:
            live_twins, settled_twins = _stem_twins(settings, entry.name)
            # Replace target: the one live copy of the SAME suffix. Never a stem
            # twin of another kind — see _same_suffix.
            replaceable = _same_suffix(live_twins, entry.name)
            dest = replaceable[0] if len(replaceable) == 1 else None
            replacing = dest is not None
            if dest is None:
                dest = _nonclobber_dest(unsorted_dir, entry.name)
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                log(f"{tag} Refreshing changed {entry.name}...")
                shutil.copy2(entry.path, dest)   # reads source, writes LOCAL only
            except OSError as exc:
                log(f"[LAN Sync] could not refresh {entry.name} "
                    f"({type(exc).__name__}: {exc}) — left on share.")
                continue
            digest = content_hash(dest)
            if meta is not None:
                registry.record(entry.path, meta[0], meta[1], sha256=digest)
            if digest is not None and digest == known.sha256:
                # Timestamp-only touch — the bytes are the ones already ingested, so
                # nothing downstream changed. Re-fingerprinted above so the next run
                # is O(1) again.
                result.unchanged += 1
                continue
            # A4-V2 — content dedup, TWIN PATH ONLY. `replacing` overwrites the one
            # authoritative copy in place and is left exactly as it was. With no
            # single copy to replace we used to stage a `-lan` twin blind; hash it
            # against every other local copy first — live, then settled, then the
            # parse cache. Identical bytes mean the twin is an artifact, not a report.
            if not replacing and digest is not None:
                note = ""
                match = _duplicate_twin(digest, live_twins, dest)
                if match is None:
                    match = _duplicate_twin(digest, settled_twins, dest)
                    if match is not None:
                        # Name the settled folder: dropping a copy because it already
                        # sits in SKIPPED_REPORTS/_PRUNED is an operator-visible call.
                        rel = match.relative_to(Path(settings.input_dir)).as_posix()
                        note = f" (matches {rel})"
                if match is not None or digest.casefold() in _indexes()[1]:
                    dest.unlink(missing_ok=True)  # only the copy made a moment ago
                    result.skipped_dupes += 1
                    log(f"{tag} Skipped duplicate content {entry.name}{note}...")
                    continue
            if index_cache is not None:          # keep an already-built index honest
                stems, digests = index_cache
                stems.add(Path(dest.name).stem.casefold())
                if digest is not None:
                    digests.add(digest.casefold())
            try:
                result.bytes_copied += dest.stat().st_size
            except OSError:
                pass
            result.modified.append(dest.name)
            if not replacing:
                log(f"{tag} Staged changed {entry.name} as {dest.name} "
                    "(no single local copy to replace)...")
            continue

        # --- ABSENT: never ingested ---------------------------------------------
        stems, digests = _indexes()
        stem_cf = Path(entry.name).stem.casefold()
        if stem_cf in stems and not size_twin:
            result.skipped_dupes += 1
            if meta is not None:
                # Fingerprint it even though nothing transferred: the content hash
                # stays unknown, but the metadata triple alone makes the NEXT run's
                # decision O(1).
                registry.record(entry.path, meta[0], meta[1])
            log(f"{tag} Up to date {entry.name}...")
            continue                             # already staged/settled — no transfer
        dest = (_lan_twin_dest(unsorted_dir, entry.name, _sizes()[1]) if size_twin
                else _nonclobber_dest(unsorted_dir, entry.name))
        try:
            unsorted_dir.mkdir(parents=True, exist_ok=True)
            log(f"{tag} Staging {entry.name}...")
            shutil.copy2(entry.path, dest)       # reads source, writes LOCAL only
        except OSError as exc:
            log(f"[LAN Sync] could not stage {entry.name} "
                f"({type(exc).__name__}: {exc}) — left on share.")
            continue
        digest = content_hash(dest)
        if digest is not None and digest.casefold() in digests:
            dest.unlink(missing_ok=True)         # byte-identical to a known report
            result.skipped_dupes += 1
            if meta is not None:
                registry.record(entry.path, meta[0], meta[1], sha256=digest)
            log(f"{tag} Skipped duplicate content {entry.name}...")
            continue
        if digest is not None:
            digests.add(digest.casefold())
        if size_twin:
            log(f"{tag} Staged {entry.name} as {dest.name} "
                "(same name, different size)...")
            _sizes()[0].setdefault(entry.name.casefold(), []).append(meta[0])
            _sizes()[1].add(dest.name.casefold())
        stems.add(stem_cf)                       # dedup within this run too
        if meta is not None:
            registry.record(entry.path, meta[0], meta[1], sha256=digest)
        try:
            result.bytes_copied += dest.stat().st_size
        except OSError:
            pass
        result.staged.append(dest.name)

    result.elapsed_s = time.perf_counter() - t0
    # Best-effort: a manifest that cannot be written costs the next run its fast
    # path, never this run's staged files.
    try:
        registry.save()
    except OSError as exc:
        log(f"[LAN Sync] could not write the ingestion registry "
            f"({type(exc).__name__}: {exc}) — next run re-checks every file.")

    return result


# ---------------------------------------------------------------------------------------
# Cutoff engine — internal-date-gated bulk sync (reset_and_sync_input.py)
# ---------------------------------------------------------------------------------------
#
# A separate entry point from :func:`sync_from_lan`. Where that one scopes by a single
# target-year folder and dedups on filename/hash for a normal ``main.py`` run, this one
# ingests EVERY report on or after a fixed internal-inspection-date cutoff — the true
# ``Date:`` printed inside each ``.docx``, never an OS timestamp. Kept apart so the fast
# ``main.py`` path never opens a ``.docx`` just to read its date.


def _read_internal_date(path, dayfirst: bool, report_no: str = ""):
    """Parse the internal inspection ``Date:`` from a ``.docx``; ``None`` if unknown.

    Opens the document (``read_tables``), pulls the ``Date:`` cell (``extract_meta``)
    and parses it (``parse_inspection_date``). Returns ``None`` for a non-docx, an
    unreadable/corrupt file, a scanned/textless report, or an unparseable value — the
    caller keeps an undetermined-date file rather than dropping a possibly-valid report.

    ``report_no`` is the file's report-number token; it repairs a truncated year in
    the cell (KB-1). A cell that names no month now returns ``None`` where it used
    to return a date built from today's clock — the verdict for a ``.docx`` is the
    same either way ("date undetermined" keeps it), so the cutoff is unaffected.
    """
    if Path(path).suffix.casefold() != ".docx":
        return None
    try:
        tables = read_tables(path)
        raw = extract_meta(tables).get("date", "")
        return parse_inspection_date(raw, dayfirst, report_no)
    except Exception:                            # noqa: BLE001 — never fail the sync
        return None


def _keep_by_date(path, name: str, cutoff: _dt.date, dayfirst: bool):
    """Decide the cutoff verdict for one staged file: ``(keep, date, reason)``.

    Date evidence, in order:

    1. **Serial year** — every report number carries ``-<YY>-``. When the EARLIEST
       possible date in that year (Jan 1) is already on/after the cutoff, the whole
       year qualifies by construction: a ``-26-`` report against a 2025-12-01 cutoff
       is kept without being opened (no ``.docx`` parse, no date needed).
    2. **Filename date** — the ``_DD.MM.YYYY`` tail the SDLN exports carry. This is
       the only date a ``.pdf`` can offer without OCR.
    3. **Internal ``Date:``** — parsed out of the ``.docx`` body.

    With no evidence at all the verdict splits by format: an undated ``.docx`` is
    KEPT (the parse may simply have failed on a valid current report, and the
    pipeline can still read it downstream), while an undated pre-cutoff-year
    ``.pdf`` is DROPPED — a scan-only 2025 report with no date signal anywhere is
    legacy, and keeping it would drag the whole pre-engagement archive in.
    """
    serial = report_serial(name)
    if serial is not None and _dt.date(2000 + serial[0], 1, 1) >= cutoff:
        return True, None, f"serial year 20{serial[0]:02d} is wholly after cutoff"

    found = filename_date(name)
    if found is None:
        # The filename's report-number token carries the year, which is what lets a
        # truncated ``Date:`` cell still yield a date here (KB-1) instead of the
        # fabricated one dateutil used to return.
        found = _read_internal_date(path, dayfirst, report_key_of(name))
    if found is not None:
        if found < cutoff:
            return False, found, f"{found.isoformat()} < {cutoff.isoformat()}"
        return True, found, "on/after cutoff"

    if Path(name).suffix.casefold() == ".pdf":
        return False, None, "undated legacy scan"
    return True, None, "date undetermined"


def _load_manifest(path) -> dict:
    """Return the manifest's ``entries`` map (``{sha256: {...}}``); ``{}`` if absent.

    A missing or corrupt manifest is treated as empty — the sync then re-derives dedup
    from the live local index and rebuilds the manifest, so a damaged file is never
    fatal. Thin wrapper over :func:`ingestion_registry.read_manifest`, kept because the
    cutoff engine only ever wants this one map.
    """
    entries = read_manifest(path).get("entries")
    return entries if isinstance(entries, dict) else {}


def _save_manifest(path, cutoff, entries: dict, files: dict | None = None) -> None:
    """Persist the manifest atomically, preserving the ``files`` fingerprint index.

    ``files`` defaults to whatever is already on disk, so writing the cutoff engine's
    ``entries`` never drops the O(1) index :func:`sync_from_lan` maintains.
    """
    if files is None:
        stored = read_manifest(path).get("files")
        files = stored if isinstance(stored, dict) else {}
    write_manifest(path, {
        "version": SCHEMA_VERSION,
        "cutoff": cutoff.isoformat() if hasattr(cutoff, "isoformat") else cutoff,
        "entries": entries,
        "files": files,
    })


@dataclass
class CutoffSyncResult:
    """Outcome of one cutoff-gated bulk sync — everything the CLI needs to log."""

    staged: list[str] = field(default_factory=list)     # filenames copied + kept
    up_to_date: int = 0                                  # already present (name/hash)
    legacy_skipped: int = 0                              # dated/undated before cutoff
    twin_skipped: int = 0                                # .pdf dropped for a .docx twin
    rejected: int = 0                                    # failed is_valid_report_filename
    roots_scanned: int = 0
    roots_reachable: int = 0
    roots_offline: int = 0
    offline_paths: list[str] = field(default_factory=list)
    bytes_copied: int = 0
    share_label: str = ""

    @property
    def staged_count(self) -> int:
        return len(self.staged)

    @property
    def unreachable_all(self) -> bool:
        """True when roots were configured but none could be reached (share down)."""
        return self.roots_scanned > 0 and self.roots_reachable == 0


def sync_since(settings, cutoff: _dt.date, *, manifest_path,
               timeout: float | None = DEFAULT_ROOT_TIMEOUT_S,
               log=_stream) -> CutoffSyncResult:
    """Copy every share report with internal inspection date ``>= cutoff`` into UnSorted.

    Read-only on the share and idempotent across runs. For each candidate:

    * **Twin preference** — a ``.pdf`` whose report key is also present as a ``.docx``
      is dropped (the editable twin wins; no redundant conversion).
    * **Dedup** — a filename already under ``input/`` skips before transfer; a
      byte-identical copy (``.parse_cache`` digest or manifest hash) is removed after.
    * **Date gate** — a ``.docx`` whose parsed ``Date:`` is ``< cutoff`` is removed as
      legacy. An undetermined-date ``.docx`` and every lone ``.pdf`` are kept.

    Staged hashes + parsed dates are recorded in the manifest at ``manifest_path``.
    Never raises: an offline share yields an empty result with ``unreachable_all`` set.
    """
    result = CutoffSyncResult()
    lan_sources = (settings.raw.get("network_ingestion") or {}).get("lan_sources") or []
    if not lan_sources:
        return result                            # feature not configured — no-op

    dayfirst = bool(getattr(settings, "dayfirst", True))
    result.share_label = _share_label(normalize_unc(lan_sources[0]))
    stems, digests = _local_index(settings)
    # One registry object holds BOTH maps, so writing the cutoff engine's content
    # entries also carries the O(1) fingerprint index forward untouched.
    registry = IngestionRegistry.load(manifest_path)
    manifest = registry.entries
    known_hashes = set(manifest.keys())
    unsorted_dir = Path(settings.input_dir) / UNSORTED_DIR

    stats: dict = {}
    entries = _collect_candidates(settings, result, lan_sources, timeout, log,
                                  min_year=cutoff.year, stats=stats)
    result.rejected = stats.get("rejected", 0)
    total = len(entries)

    # Twin preference: a .pdf whose report key also appears as a .docx is dropped.
    # Built across ALL roots at once, so a twin split over two method roots still
    # resolves to the editable copy.
    docx_keys = {report_key_of(e.name) for e in entries
                 if Path(e.name).suffix.casefold() == ".docx"}

    for index, entry in enumerate(entries, 1):
        tag = f"[LAN Sync {index}/{total}]"
        name = entry.name
        suffix = Path(name).suffix.casefold()
        if suffix == ".pdf" and report_key_of(name) in docx_keys:
            result.twin_skipped += 1
            log(f"{tag} Skipped twin PDF {name}...")
            continue
        # Metadata is free here (cached by the scandir walk) — recorded on every file
        # this engine actually ingests or recognises, so the fast sync_from_lan path
        # inherits a warm registry from a bulk reset run.
        meta = _entry_metadata(entry)
        stem_cf = Path(name).stem.casefold()
        if stem_cf in stems:
            result.up_to_date += 1
            if meta is not None:
                registry.record(entry.path, meta[0], meta[1])
            log(f"{tag} Up to date {name}...")
            continue                             # already staged/settled — no transfer

        dest = _nonclobber_dest(unsorted_dir, name)
        try:
            unsorted_dir.mkdir(parents=True, exist_ok=True)
            log(f"{tag} Staging {name}...")
            shutil.copy2(entry.path, dest)       # reads source, writes LOCAL only
        except OSError as exc:
            log(f"[LAN Sync] could not stage {name} "
                f"({type(exc).__name__}: {exc}) — left on share.")
            continue

        digest = content_hash(dest)
        digest_cf = digest.casefold() if digest is not None else None
        if digest_cf is not None and (digest_cf in digests or digest in known_hashes):
            dest.unlink(missing_ok=True)         # byte-identical to a known report
            result.up_to_date += 1
            if meta is not None:
                registry.record(entry.path, meta[0], meta[1], sha256=digest)
            log(f"{tag} Skipped duplicate content {name}...")
            continue

        keep, keep_date, reason = _keep_by_date(dest, name, cutoff, dayfirst)
        if not keep:
            dest.unlink(missing_ok=True)         # legacy — before the cutoff
            result.legacy_skipped += 1
            log(f"{tag} Skipped legacy {name} ({reason})...")
            continue

        if digest is not None:
            digests.add(digest_cf)
            known_hashes.add(digest)
            manifest[digest] = {
                "name": dest.name,
                "date": keep_date.isoformat() if keep_date else None,
                "staged_at": _dt.datetime.now().isoformat(timespec="seconds"),
            }
        stems.add(stem_cf)                       # dedup within this run too
        if meta is not None:
            registry.record(entry.path, meta[0], meta[1], sha256=digest)
        try:
            result.bytes_copied += dest.stat().st_size
        except OSError:
            pass
        result.staged.append(dest.name)

    registry.set_entries(manifest, cutoff)
    registry.save()
    return result
