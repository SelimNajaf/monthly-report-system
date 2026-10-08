"""Coverage audit — every source file under ``input/`` gets exactly one outcome.

Off by default (``audit.coverage_report: false``). When on, ``main.py`` feeds a
:class:`Collector` with what the run already knows — the parse set, every
quarantine, discovery's groups, each built report's rows and ``report.skipped``
notes, the groups that were not rendered — and at run end:

* writes ``output/coverage_<YYYY-MM-DD>.md`` (2026+ first, then all months);
* prints ONE new line,
  ``  Coverage: N sources, M in documents, K explained elsewhere, U UNEXPLAINED``,
  and a second one (R4-D), ``  İtem English (2026+): V value(s), R row(s) not in
  az.json``, for the İtem values listed in the report's own section.

Nothing is hashed, moved or written under ``input/``: the source universe is a
directory listing (name, folder, size). The LAN section reads the ingestion
manifest (``.state/network_sync_manifest.json``) — read-only.

``U > 0`` is a signal for the operator, never a failure: the run's exit code does
not depend on it.

The stdout line is shaped so no GUI parser claims it: two-space indent, does not
start with ``[``, does not end in ``.pdf``, carries none of the console's
warning words. Pinned by ``tests/test_coverage_audit.py``.

The file name does not match ``compiled_monthly_report_*.json``, so the
uploader's sidecar sweep and the ledger never see it.
"""

from __future__ import annotations

import collections
import datetime as _dt
import json
import re
from pathlib import Path

from .naming import PDF_ARCHIVE_DIR, PRUNED_DIR, QUARANTINE_DIR, UNSORTED_DIR
from .report_identity import report_key_of

#: Report file kinds the audit counts as sources.
SOURCE_EXTS = (".docx", ".pdf")

#: First year (two-digit report-number year) of the operator's lists (S1).
FOCUS_YY = 26

#: Outcome buckets, in report order. ``IN_DOCS`` and ``UNEXPLAINED`` are the two
#: ends; everything between is "explained elsewhere".
IN_DOCS = "in documents"
UNEXPLAINED = "UNEXPLAINED"
BUCKETS = (IN_DOCS, "from delete folder", "standard gate", "mismatch copy",
           "duplicate Report №", "merged transposition", "excluded (ASR/ARS, client)", "other note", "quarantined",
           "quarantine name conflict", "pruned", "archived PDF twin",
           "not grouped (volume floor)", "group not rendered", "out of scope",
           "UnSorted unmatched", UNEXPLAINED)

#: ``report.skipped`` reasons that only say "this file belongs to ANOTHER group"
#: (every group's build names every other file this way). Not an outcome.
_ROUTING = re.compile(r"^(date .* not in \d{4}-\d{2}|method \S* != |client \S* != )")

_EXCLUDED = re.compile(r"^client \S+ (inactive/excluded|below min_total_client_volume)")

_SERIES = re.compile(r"^(?P<pre>.+?)-(?P<yy>\d{2})-(?P<n>\d{1,4})(?!\d)")
_LAN_TAIL = re.compile(r"-lan\d*$", re.IGNORECASE)


def is_enabled(settings) -> bool:
    """True when ``audit.coverage_report`` is literally ``true`` (default off)."""
    block = (getattr(settings, "raw", None) or {}).get("audit") or {}
    return block.get("coverage_report", False) is True


def coverage_line(n: int, m: int, k: int, u: int) -> str:
    """The one stdout line. Shape pinned against every GUI regex."""
    return (f"  Coverage: {n} sources, {m} in documents, "
            f"{k} explained elsewhere, {u} UNEXPLAINED")


def _pick(reasons) -> str | None:
    """The reason that explains a file best: the first outcome-bearing one, by
    bucket order (standard gate before a generic note), routing notes ignored."""
    real = [r for r in reasons if not _ROUTING.match(r)]
    if not real:
        return None
    return min(real, key=lambda r: BUCKETS.index(_bucket(r)))


def _bucket(reason: str) -> str:
    """Map a ``report.skipped`` reason to its bucket."""
    from . import document_aggregator, duplicate_identity, report_no_mismatch
    if reason.startswith(document_aggregator.DELETE_FOLDER_REASON):
        return "from delete folder"
    if reason.startswith(document_aggregator.UNAPPROVED_STANDARD_REASON):
        return "standard gate"
    if reason.startswith(report_no_mismatch.BLOCK_REASON):
        return "mismatch copy"
    if reason.startswith("duplicate Report №"):
        return "duplicate Report №"
    if reason.startswith(duplicate_identity.DUPLICATE_IDENTITY_MERGED):
        return "merged transposition"
    if reason.startswith("ASR/ARS excluded") or _EXCLUDED.match(reason):
        return "excluded (ASR/ARS, client)"
    return "other note"


def series_of(name: str):
    """``(prefix, yy, number)`` of a file name's report key, or ``None``."""
    m = _SERIES.match(report_key_of(name) or "")
    if not m:
        return None
    return m.group("pre").upper(), int(m.group("yy")), int(m.group("n"))


class Collector:
    """What one ``main.py`` run knows about its sources, gathered as it goes."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.input_dir = Path(settings.input_dir)
        self.parsed: set[str] = set()              # normalised paths read this run
        self.quarantined: dict[str, str] = {}      # file name -> reason (this run)
        self.unmatched: set[str] = set()           # UnSorted names left in place
        self.members: dict[str, tuple] = {}        # path -> (month, client)
        self.selected: set[tuple] = set()          # (month, client) in scope
        self.in_docs: dict[str, tuple] = {}        # path -> (doc tag, client)
        self.notes: dict[str, list] = collections.defaultdict(list)  # name -> reasons
        self.not_rendered: dict[str, str] = {}     # path -> why its group was not
        self.conflicts: set[str] = set()           # parsed, dropped, not moved
        self.items: list[tuple[str, str, str]] = []  # (month, doc tag, raw İtem)
        self.english: list[tuple[str, int, list[str]]] = []  # set by write()

    # --- feeding ----------------------------------------------------------------

    @staticmethod
    def _k(path) -> str:
        return str(Path(path)).casefold()

    def add_parsed(self, paths) -> None:
        self.parsed.update(self._k(p) for p in paths)

    def add_quarantined(self, pairs) -> None:
        for name, reason in pairs:
            self.quarantined.setdefault(str(name).casefold(), reason)

    def add_unmatched(self, rels) -> None:
        self.unmatched.update(Path(r).name.casefold() for r in rels)

    def add_discovery(self, cache, members, selected) -> None:
        """After ``discover_groups``: who is grouped, and who silently left the cache.

        A parsed file that is no longer in ``cache`` and was not quarantined was
        dropped on a quarantine whose move failed (name conflict — left in place).
        """
        for (month, client), paths in (members or {}).items():
            for p in paths:
                self.members[self._k(p)] = (month, client)
        self.selected = {(g[0], g[1]) for g in selected}
        live = {self._k(p) for p in cache}
        for p in self.parsed - live:
            if Path(p).name not in self.quarantined:
                self.conflicts.add(p)

    def add_report(self, month: str, client: str, tag: str, report,
                   rendered: str | None) -> None:
        """One built report. ``rendered`` is ``None`` when it is a deliverable
        (rendered or reused), else why it was not (``"no rows"``, ``"low volume"``)."""
        for name, reason in report.skipped:
            self.notes[str(name).casefold()].append(reason)
        if rendered is not None:
            for p, (m, c) in self.members.items():
                if (m, c) == (month, client):
                    self.not_rendered.setdefault(p, rendered)
            return
        for row in report.rows:
            src = getattr(row, "source_path", None)
            if src is not None:
                self.in_docs.setdefault(self._k(src), (tag, client))
            self.items.append((month, tag, getattr(row, "item_detail", "") or ""))

    # --- classification ---------------------------------------------------------

    def _quarantine_reasons(self) -> dict[str, str]:
        """Reason tags recorded by earlier runs (``.state/quarantine_reasons.json``)."""
        path = Path(self.settings.project_root) / ".state" / "quarantine_reasons.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k).casefold(): str(v) for k, v in (data.get("tags") or {}).items()}

    def sources(self) -> list[Path]:
        if not self.input_dir.is_dir():
            return []
        return sorted(p for p in self.input_dir.rglob("*")
                      if p.suffix.casefold() in SOURCE_EXTS
                      and not p.name.startswith("~$") and p.is_file())

    def classify(self) -> list[dict]:
        """One row per source file: name, folder, client, bucket, detail."""
        from .method_registry import resolve_client
        earlier = self._quarantine_reasons()
        out = []
        for path in self.sources():
            k = self._k(path)
            name_cf = path.name.casefold()
            try:
                top = path.relative_to(self.input_dir).parts[0]
            except (ValueError, IndexError):
                top = ""
            top_cf = top.casefold()
            client = ""
            if k in self.in_docs:
                tag, client = self.in_docs[k]
                bucket, detail = IN_DOCS, tag
            elif top_cf == PRUNED_DIR.casefold():
                bucket, detail = "pruned", f"input/{PRUNED_DIR}/"
            elif top_cf == QUARANTINE_DIR.casefold():
                why = (self.quarantined.get(name_cf) or earlier.get(name_cf)
                       or "no recorded reason")
                bucket, detail = "quarantined", why
            elif _pick(self.notes.get(name_cf, ())) is not None:
                detail = _pick(self.notes[name_cf])
                bucket = _bucket(detail)
            elif k in self.conflicts:
                bucket, detail = "quarantine name conflict", "left in place"
            elif k in self.not_rendered:
                bucket, detail = "group not rendered", self.not_rendered[k]
            elif k in self.members and self.members[k] not in self.selected:
                bucket, detail = "out of scope", "%s %s" % self.members[k]
            elif top_cf == PDF_ARCHIVE_DIR.casefold() and k not in self.parsed:
                bucket, detail = "archived PDF twin", "a .docx holds its report key"
            elif k in self.parsed and k not in self.members:
                bucket, detail = "not grouped (volume floor)", "left in place"
            elif top_cf == UNSORTED_DIR.casefold() and name_cf in self.unmatched:
                bucket, detail = "UnSorted unmatched", "no method matched"
            else:
                bucket, detail = UNEXPLAINED, ""
            if not client:
                member = self.members.get(k)
                client = member[1] if member else resolve_client(
                    report_key_of(path.name), self.settings)[0]
            s = series_of(path.name)
            out.append({"path": path, "name": path.name, "folder": top,
                        "client": client, "bucket": bucket, "detail": detail,
                        "series": s, "yy": s[1] if s else None})
        return out

    # --- LAN manifest (read-only) -----------------------------------------------

    def lan_size_mismatches(self, rows) -> tuple[list[tuple], int]:
        """Manifest files never transferred whose name exists locally with a
        different size: ``([(share-relative path, size, [local sizes])], delete_count)``."""
        from .services.network_ingestion import under_delete_folder
        path = Path(self.settings.project_root) / ".state" / "network_sync_manifest.json"
        try:
            files = json.loads(path.read_text(encoding="utf-8")).get("files") or {}
        except (OSError, ValueError):
            return [], 0
        sizes: dict[str, list[int]] = collections.defaultdict(list)
        for r in rows:
            try:
                size = r["path"].stat().st_size
            except OSError:
                continue
            base = _LAN_TAIL.sub("", r["path"].stem) + r["path"].suffix
            sizes[base.casefold()].append(size)
        found, deleted = [], 0
        for rec in files.values():
            unc = str(rec.get("unc_path") or "")
            parts = re.split(r"[\\/]", unc)
            if under_delete_folder(unc):
                deleted += 1
                continue
            if rec.get("sha256"):
                continue
            local = sizes.get(parts[-1].casefold())
            if local and rec.get("size") not in local:
                found.append(("\\".join(parts[4:]) or parts[-1], rec.get("size"),
                              sorted(local)))
        return sorted(found), deleted


# --------------------------------------------------------------------------------
# Report


def _gaps(rows, yy_filter):
    """Sequence gaps per series, over the numbers that ARE in documents.

    Returns ``[(series label, number, [(file, bucket)] )]`` — an empty list of
    files means no source file anywhere under ``input/``.
    """
    in_doc = collections.defaultdict(set)
    anywhere = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows:
        s = r["series"]
        if s is None or not yy_filter(s[1]):
            continue
        anywhere[(s[0], s[1])][s[2]].append((r["name"], r["bucket"]))
        if r["bucket"] == IN_DOCS:
            in_doc[(s[0], s[1])].add(s[2])
    gaps = []
    for (pre, yy), nums in sorted(in_doc.items()):
        for n in range(min(nums), max(nums) + 1):
            if n not in nums:
                gaps.append((f"{pre}-{yy:02d}", n, anywhere[(pre, yy)].get(n, [])))
    return gaps


def _client_table(rows) -> list[str]:
    per = collections.defaultdict(collections.Counter)
    for r in rows:
        per[r["client"] or "?"][r["bucket"]] += 1
    used = [b for b in BUCKETS if any(c[b] for c in per.values())]
    lines = ["| client | " + " | ".join(used) + " | total |",
             "|---|" + "--:|" * (len(used) + 1)]
    for client in sorted(per):
        c = per[client]
        lines.append(f"| {client} | " + " | ".join(str(c[b]) for b in used)
                     + f" | {sum(c.values())} |")
    return lines


def _totals(rows) -> tuple[int, int, int, int]:
    n = len(rows)
    m = sum(1 for r in rows if r["bucket"] == IN_DOCS)
    u = sum(1 for r in rows if r["bucket"] == UNEXPLAINED)
    return n, m, n - m - u, u


#: Letters only Azerbaijani writes: a value holding one is not English.
_AZ_LETTERS = re.compile(r"[əğıöüşçƏĞİÖÜŞÇ]")
#: A run of three Latin letters: ``DB-2``, ``M1-M1A`` and ``10E-389-01-A`` have none.
_LATIN_WORD = re.compile(r"[A-Za-z]{3,}")
#: The translator's gap marker (``Translator.controlled``); never on İtem today.
_GAP_MARKER = "[AZ?]"


def looks_english(text: str) -> bool:
    """A Latin word and no Azerbaijani letter. Deliberately loose: an ASCII-only
    Azerbaijani value ("AYS sistemi") or an identifier with a word in it is listed
    too — the list is for the operator to read, never a failure."""
    return bool(_LATIN_WORD.search(text)) and not _AZ_LETTERS.search(text)


def english_items(collector: Collector) -> list[tuple[str, int, list[str]]]:
    """2026+ İtem values of rendered documents that ``az.json`` does not translate
    and that look English (or carry the gap marker): ``[(value, rows, [doc tags])]``.

    Every sidecar row counts, including the values a ``range_item: dominant`` PDF
    line does not show. ``[]`` when the dictionary cannot be read."""
    from .translator import load_dictionary
    path = getattr(collector.settings, "translations_path", None)
    if path is None:
        return []
    try:
        dictionary = load_dictionary(path)
    except (OSError, ValueError):
        return []
    found: dict[str, list[str]] = collections.defaultdict(list)
    for month, tag, item in collector.items:
        text = item.strip()
        if not text or month < f"20{FOCUS_YY}-01":
            continue
        if _GAP_MARKER not in text and (text.lower() in dictionary
                                        or not looks_english(text)):
            continue
        found[text].append(tag)
    return sorted((v, len(t), sorted(set(t))) for v, t in found.items())


def item_line(english) -> str:
    """The second stdout line: İtem values still in English, 2026+."""
    rows = sum(n for _v, n, _t in english)
    return (f"  İtem English (20{FOCUS_YY}+): {len(english)} value(s), "
            f"{rows} row(s) not in az.json")


def render(rows, lan: tuple[list, int], today: str, english=()) -> str:
    """The markdown report. 2026+ first (S1), then all months."""
    focus = [r for r in rows if r["yy"] is not None and r["yy"] >= FOCUS_YY]
    L: list[str] = [f"# Coverage — {today}", "",
                    "Every report file under `input/` (working folders, `PDF_ARCHIVE`, "
                    "`SKIPPED_REPORTS`, `_PRUNED`, `UnSorted`) with exactly one outcome. "
                    "Year = the report number's `-YY-`. Built from this run's own data; "
                    "nothing hashed, moved or renamed.", ""]

    def section(title, sel, yy_filter, full_gaps):
        n, m, k, u = _totals(sel)
        L.extend([f"## {title}", "",
                  f"**{n} sources, {m} in documents, {k} explained elsewhere, "
                  f"{u} UNEXPLAINED.**", "", "### Outcomes per client", ""])
        L.extend(_client_table(sel))
        L.extend(["", f"### UNEXPLAINED ({u})", ""])
        unexplained = [r for r in sel if r["bucket"] == UNEXPLAINED]
        if unexplained:
            L.extend(["| file | folder | client |", "|---|---|---|"])
            L.extend(f"| `{r['name']}` | {r['folder']} | {r['client']} |"
                     for r in unexplained)
        else:
            L.append("None.")
        gaps = _gaps(rows, yy_filter)
        with_src = [g for g in gaps if g[2]]
        without = [g for g in gaps if not g[2]]
        L.extend(["", f"### Sequence gaps: {len(gaps)} — {len(with_src)} with a "
                      f"source file, {len(without)} with none under `input/`", ""])
        if full_gaps:
            L.append("Gap = a number between the lowest and highest number of a series "
                     "that is in a document, itself in no document.")
            L.extend(["", "| series | № | source file(s) → outcome |", "|---|--:|---|"])
            for label, num, files in gaps:
                what = "; ".join(f"`{f}` → {b}" for f, b in files) or "**no file**"
                L.append(f"| {label} | {num:03d} | {what} |")
        else:
            per = collections.Counter(label for label, _n, f in without)
            L.extend(["| series | gaps with no file |", "|---|--:|"])
            L.extend(f"| {s} | {c} |" for s, c in sorted(per.items()))
        L.append("")

    section(f"20{FOCUS_YY}+ (report-number year)", focus,
            lambda yy: yy >= FOCUS_YY, True)

    std = sorted((r["name"], r["detail"]) for r in focus if r["bucket"] == "standard gate")
    L.extend([f"### Standard gate omissions, 20{FOCUS_YY}+ ({len(std)})", "",
              "The full list the run-end `[unapproved standard]` print caps at 10.", ""])
    if std:
        L.extend(["| file | reason |", "|---|---|"])
        L.extend(f"| `{n}` | {d} |" for n, d in std)
    else:
        L.append("None.")
    L.extend(["", f"### İtem / Detal not in az.json, 20{FOCUS_YY}+ ({len(english)})", "",
              "Rendered documents, every sidecar row (a `range_item: dominant` PDF line "
              "shows one value of its range). Listed: no `az.json` entry, a Latin word and "
              "no Azerbaijani letter, or the `[AZ?]` marker. An ASCII-only Azerbaijani "
              "value or an identifier may be listed too; the operator decides.", ""])
    if english:
        L.extend(["| İtem | rows | documents |", "|---|--:|---|"])
        L.extend(f"| `{v}` | {n} | {', '.join(t)} |".replace("\n", "⏎")
                 for v, n, t in english)
    else:
        L.append("None.")
    found, deleted = lan
    focus_lan = [f for f in found if (series_of(f[0].split("\\")[-1]) or (0, 0))[1]
                 >= FOCUS_YY]
    L.extend(["", f"### LAN: same name, different size, never staged, "
                  f"20{FOCUS_YY}+ ({len(focus_lan)})", "",
              "From the ingestion manifest. `network_ingestion.stage_size_mismatch: true` "
              "stages these as `-lan` twins. Files under a share folder named `delete` "
              f"are never staged and not listed ({deleted} in the manifest).", ""])
    if focus_lan:
        L.extend(["| share path | LAN size | local size(s) |", "|---|--:|---|"])
        L.extend(f"| `{p}` | {s} | {', '.join(map(str, ls))} |" for p, s, ls in focus_lan)
    else:
        L.append("None.")
    L.append("")

    section("All months", rows, lambda yy: True, False)
    L.extend(["### Outcome totals, all months", "", "| outcome | files |", "|---|--:|"])
    c = collections.Counter(r["bucket"] for r in rows)
    L.extend(f"| {b} | {c[b]} |" for b in BUCKETS if c[b])
    L.extend(["", f"LAN same-name/different-size never staged, all years: {len(found)}.", ""])
    return "\n".join(L) + "\n"


def write(collector: Collector, output_dir) -> tuple[Path, tuple[int, int, int, int]]:
    """Classify, write ``coverage_<today>.md`` under ``output_dir``; return the path
    and the run totals ``(N, M, K, U)``."""
    rows = collector.classify()
    today = _dt.date.today().isoformat()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"coverage_{today}.md"
    collector.english = english_items(collector)
    path.write_text(render(rows, collector.lan_size_mismatches(rows), today,
                           collector.english), encoding="utf-8")
    return path, _totals(rows)
