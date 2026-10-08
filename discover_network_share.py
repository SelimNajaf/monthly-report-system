#!/usr/bin/env python3
"""LAN network-share source discovery & structure mapping (STRICTLY READ-ONLY).

Raw NDT inspection reports (.docx / .pdf) live on a remote SMB share
(``\\\\<host>\\<share>\\...``) split into method root folders
(Hardness Test, Dye Penetrant, UT, X-ray, ...). Before any automated staging into
the local ``input/`` tree, this scanner catalogs the remote structure: file counts
by extension, the ``Method -> Year -> Client -> Files`` layout, twin ``.pdf``/``.docx``
pairs (the same report in both formats), file sizes and last-modified dates.

    python discover_network_share.py            # scan configured lan_sources
    python discover_network_share.py --json     # also dump the raw result as JSON

READ-ONLY GUARANTEE: the scanner only ever *reads* the share — it walks directories
(``os.scandir``) and reads cached ``.stat()`` data. It never opens a network file
for writing and
never moves, renames, copies or deletes anything under the share. The only file it
writes is the local ``LAN_NETWORK_DISCOVERY_REPORT.md`` at the project root.

GRACEFUL OFFLINE: each configured root is scanned inside a guard, so an unreachable
host, a permission error or a timeout is recorded as "unreachable" and the scan
moves on to the next root — the run never crashes and always emits a report.

Actual copy-into-``input/`` staging is a LATER phase; this deliverable only maps the
source and proposes the staging strategy (see the report's final section).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

#: Per-root wall-clock budget. A pingable-but-unshared host makes Windows block on
#: SMB session negotiation for tens of seconds per path; without a bound one dead
#: root could stall the whole scan. Each root is scanned in a worker thread and,
#: if it overruns this budget, recorded as an unreachable "timeout" — the run
#: always finishes and always emits a report (the spec's graceful-timeout rule).
DEFAULT_ROOT_TIMEOUT_S = 20.0

# Windows consoles default to a legacy codepage (cp1251) that cannot encode the
# Azerbaijani / Turkish characters carried in these paths (BOS-ŞELF, PMI-, Cyrillic
# "Ferrite content" siblings); force UTF-8 so prints never crash mid-scan.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from monthly_report import method_registry  # noqa: E402
from monthly_report.config import load_settings  # noqa: E402
from monthly_report.report_identity import report_key_of  # noqa: E402

REPORT_NAME = "LAN_NETWORK_DISCOVERY_REPORT.md"

#: Report document extensions we care about; everything else is bucketed "other".
DOC_EXTS = (".docx", ".pdf")

#: Extensions a *name* may carry and still be a real report. Legacy ".doc" is
#: recognised here (the share still holds a few) but is NOT in the sync's
#: STAGE_EXTS — python-docx cannot open it, so it is reported, not staged.
REPORT_EXTS = (".docx", ".pdf", ".doc")

#: A folder name that looks like a year subfolder, e.g. "DP-2026", "RT-2026",
#: "2005-2026", "Ferrite-2026". Any 4-digit run 19xx/20xx marks it as year-bearing.
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")

# --- Report-filename classification -----------------------------------------------------
#
# Every real report number ends in a "-<YY>-<NNN>" serial, in one of two orders:
#
#     client-first   AZF-DP-W1-25-39   G-DP-25-001   KF-HrT-25-001 (1901)
#     method-first   DP-SDLN-25-005(F1798)6"-15E440-02-A_16.09.2025
#
# The trailing job/date noise is stripped by report_identity.report_key_of (the same
# leading-token rule the twin matcher already uses), so these patterns only ever see
# the clean token.

#: The "-<YY>-<NNN>" serial tail, with an optional retest/marker suffix (R1, ASR).
_SERIAL_TAIL = re.compile(r"-(\d{2})-(\d{1,4})([A-Za-z0-9]*)$")

#: A DD.MM.YYYY / DD-MM-YYYY date embedded in a filename (the SDLN export tail).
_FILENAME_DATE = re.compile(r"(\d{2})[.\-](\d{2})[.\-](20\d{2})")

#: Name prefixes that mark a non-report: Word lock files (``~$Report.docx``) and
#: editor/backup droppings. Never staged, never counted.
JUNK_PREFIXES = ("~$", ".~", "$")

#: Folder-name substrings that mark a utility / administrative subtree rather than
#: a client folder. Matched case-folded as a substring so "Old reports",
#: "TEMPLATES" and "Report Forms 2024" all prune.
UTILITY_FOLDER_TOKENS = (
    "template", "şablon", "sablon", "archive", "arxiv", "backup", "old",
    "report form", "blank", "certificate", "sertifikat", "equipment",
    "personnel", "procedure", "calibration", "kalibrasiya", "draft",
)

#: client_prefixes cache, keyed by id(settings.raw) — same shape as
#: method_registry._DETECT_CACHE, so a settings reload rebuilds it.
_PREFIX_CACHE: dict[int, frozenset[str]] = {}


def client_prefixes(settings) -> frozenset[str]:
    """Every client token the registry can recognise, upper-cased.

    The union of each ``clients[*].code`` and its ``prefixes`` list, so both the
    operator prefix (``U``, ``KF``, ``G``) and the registry code (``UBOC``,
    ``GEMZA``, ``SDLN``) are accepted — share filenames use both forms
    (``U-DP-25-001`` and ``UBOC-PMI-25-001`` are the same client).

    Config-driven: adding a client to ``settings.yaml`` widens the gate, no code
    change. Retired clients (``active: false``) stay IN the set on purpose — the
    pipeline recognises them and then quarantines them downstream; dropping them
    at the LAN boundary would lose that audit trail.
    """
    key = id(settings.raw)
    cached = _PREFIX_CACHE.get(key)
    if cached is not None:
        return cached
    tokens: set[str] = set()
    for code, spec in (settings.raw.get("clients") or {}).items():
        spec = spec or {}
        for value in (str(spec.get("code") or code), *(spec.get("prefixes") or [])):
            token = str(value).strip().upper()
            if token:
                tokens.add(token)
    result = frozenset(tokens)
    _PREFIX_CACHE[key] = result
    return result


def report_serial(name: str) -> tuple[int, int] | None:
    """``("KF-DP-25-001(1896).docx")`` -> ``(25, 1)``; ``None`` when there is none.

    Returns the ``(2-digit year, sequence)`` of the report number's serial tail.
    A name with no such tail is not a report — administrative documents, price
    lists, certificates and scans all fail here.
    """
    m = _SERIAL_TAIL.search(report_key_of(name))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def filename_date(name: str) -> dt.date | None:
    """The DD.MM.YYYY date carried in a filename, or ``None``.

    The SDLN exports append the inspection date to the report number
    (``..._16.09.2025.docx``). This is the ONLY date signal a ``.pdf`` has — its
    internal ``Date:`` cell is unreadable without OCR — so it drives the cutoff
    gate for scan-only reports. The LAST match wins (the serial's ``-25-`` cannot
    match, but a job reference might).
    """
    matches = _FILENAME_DATE.findall(Path(str(name or "")).stem)
    for day, month, year in reversed(matches):
        try:
            return dt.date(int(year), int(month), int(day))
        except ValueError:
            continue                             # 32.13.2025 — not a date, keep looking
    return None


def is_utility_folder(name: str) -> bool:
    """True for an administrative / template subtree that holds no client reports."""
    folded = str(name or "").casefold()
    return any(token in folded for token in UTILITY_FOLDER_TOKENS)


def is_valid_report_filename(name: str, settings) -> bool:
    """True when a share filename is a real NDT report we should ingest.

    Five gates, cheapest first:

    1. no junk prefix (``~$`` Word lock files, editor droppings, dotfiles);
    2. a report extension (``.docx`` / ``.pdf`` / legacy ``.doc``);
    3. a ``-<YY>-<NNN>`` serial tail (:func:`report_serial`) — this is what rejects
       ``Report Forms.docx``, ``Sertifikat.pdf``, ``Price list 2026.docx``;
    4. a registered NDT method token (``DP``/``PT``, ``MT``/``MPI``, ``RT``, ``UT``/
       ``UTM``/``UTR``, ``PMI``, ``FC``, ``HrT``) — via
       :func:`method_registry.detect_method`;
    5. a client token that is in :func:`client_prefixes` — this is what rejects an
       unapproved / utility subfolder's files (``XYZ-DP-26-001.docx``) and a
       clientless number (``MT-26-001.docx``).

    Both name orders pass — ``detect_method``/``detect_client`` already handle
    client-first (``AZF-DP-W1-25-39``) and method-first (``UT-SDLN-25-044``).
    """
    raw = str(name or "").strip()
    if not raw or raw.startswith(JUNK_PREFIXES) or raw.startswith("."):
        return False
    path = Path(raw)
    if path.suffix.casefold() not in REPORT_EXTS:
        return False
    if report_serial(path.name) is None:
        return False
    key = report_key_of(path.name)
    if method_registry.detect_method(key, settings) == "NDT":
        return False
    return method_registry.detect_client(key, settings) in client_prefixes(settings)


# --- Data model (pure dataclasses — trivially serialisable for --json / tests) ----------


@dataclass
class RootScan:
    """Everything discovered under one configured network root."""

    raw_path: str                              # the UNC string exactly as configured
    normalized: str                            # normalize_unc(raw_path)
    reachable: bool = True
    error: str = ""                            # populated when reachable is False
    total_files: int = 0
    ext_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    total_bytes: int = 0
    newest_mtime: float | None = None
    year_folders: set[str] = field(default_factory=set)
    client_folders: set[str] = field(default_factory=set)
    extra_folders: set[str] = field(default_factory=set)   # nested "Report/" etc.
    twin_pairs: int = 0
    # Nested Method -> Year -> Client -> [filenames] tree (files list capped for the
    # report; full counts live in the flat totals above).
    tree: dict = field(default_factory=dict)

    @property
    def docx(self) -> int:
        return self.ext_counts.get(".docx", 0)

    @property
    def pdf(self) -> int:
        return self.ext_counts.get(".pdf", 0)


@dataclass
class DiscoveryResult:
    """Aggregate of every scanned root plus run metadata."""

    roots: list[RootScan] = field(default_factory=list)
    generated_at: str = ""

    @property
    def reachable_roots(self) -> list[RootScan]:
        return [r for r in self.roots if r.reachable]

    @property
    def total_files(self) -> int:
        return sum(r.total_files for r in self.roots)

    @property
    def total_docx(self) -> int:
        return sum(r.docx for r in self.roots)

    @property
    def total_pdf(self) -> int:
        return sum(r.pdf for r in self.roots)

    @property
    def total_twins(self) -> int:
        return sum(r.twin_pairs for r in self.roots)

    @property
    def total_bytes(self) -> int:
        return sum(r.total_bytes for r in self.roots)


# --- Pure helpers (no network — unit-testable in isolation) -----------------------------


def normalize_unc(raw: str) -> str:
    r"""Canonicalise a UNC / local path string for display and comparison.

    Collapses mixed ``/`` and ``\`` separators to a single backslash, squeezes
    repeated separators inside the path, and strips a trailing separator — while
    preserving the leading ``\\`` of a UNC root (``\\host\share\...``). Pure string
    operation: it never touches the filesystem, so it works offline and in tests.
    """
    if raw is None:
        return ""
    s = str(raw).strip().replace("/", "\\")
    is_unc = s.startswith("\\\\")
    # Squash any run of separators to one, then re-attach the UNC double-lead.
    body = re.sub(r"\\+", "\\\\", s.lstrip("\\"))
    out = ("\\\\" + body) if is_unc else body
    # Drop a lone trailing separator, but never reduce "\\host" style leads.
    if len(out) > 2 and out.endswith("\\"):
        out = out.rstrip("\\")
    return out


def is_year_folder(name: str) -> bool:
    """True when a folder name carries a 4-digit year token (DP-2026, 2005-2026)."""
    return bool(_YEAR_RE.search(str(name or "")))


def find_twin_pairs(filenames) -> list[str]:
    """Stems that exist as BOTH ``.pdf`` and ``.docx`` (same report, two formats).

    Grouped case-folded so ``Report.PDF`` twins ``report.docx``. Returns the sorted
    list of twinned stems; ``len(...)`` is the twin-pair count.
    """
    by_stem: dict[str, set[str]] = defaultdict(set)
    for fn in filenames:
        p = Path(str(fn))
        ext = p.suffix.casefold()
        if ext in DOC_EXTS:
            by_stem[p.stem.casefold()].add(ext)
    return sorted(stem for stem, exts in by_stem.items()
                  if ".pdf" in exts and ".docx" in exts)


# --- Scanning (the only network-touching code — read-only) ------------------------------


def scan_root(root: Path, raw_path: str | None = None, file_cap: int = 15) -> RootScan:
    """Recursively catalog one root, read-only. Never raises on an unreachable path.

    Directory levels are classified by depth relative to the root:
    ``root`` == the NDT method, depth-1 == year subfolder (DP-2026), depth-2 ==
    client subfolder (UBOC), anything deeper == an "extra" nesting (e.g. ``Report/``).
    Each file contributes to the extension counts, byte total and newest-mtime; twin
    ``.pdf``/``.docx`` pairs are detected per client folder. ``file_cap`` bounds how
    many filenames are retained per leaf in the human-readable tree (totals are exact
    regardless).
    """
    root = Path(root)
    raw = raw_path if raw_path is not None else str(root)
    scan = RootScan(raw_path=raw, normalized=normalize_unc(raw))

    if not root.exists():
        scan.reachable = False
        scan.error = "path not found / share offline or unmapped"
        return scan

    method_name = root.name
    tree: dict = scan.tree
    # Explicit os.scandir walk (not os.walk): on Windows a DirEntry carries the
    # size/mtime returned by the directory enumeration itself, so entry.stat() is
    # served from that cache with NO extra SMB round-trip. Over a remote share with
    # thousands of files this is the difference between seconds and many minutes.
    stack: list[Path] = [root]
    try:
        while stack:
            cur = stack.pop()
            rel_parts = cur.relative_to(root).parts     # () at the root itself
            depth = len(rel_parts)
            year = rel_parts[0] if depth >= 1 else "(root)"
            client = rel_parts[1] if depth >= 2 else "(none)"

            if depth >= 1 and is_year_folder(rel_parts[0]):
                scan.year_folders.add(rel_parts[0])
            if depth >= 2:
                scan.client_folders.add(rel_parts[1])
            if depth >= 3:
                # e.g. Method/DP-2026/UBOC/Report -> "Report" is the extra nesting.
                scan.extra_folders.add(rel_parts[-1])

            try:
                with os.scandir(cur) as it:
                    entries = list(it)
            except OSError:
                continue                          # unreadable subdir — skip, keep going

            doc_names: list[str] = []
            for entry in entries:
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    is_dir = False
                if is_dir:
                    stack.append(Path(entry.path))
                    continue
                ext = Path(entry.name).suffix.casefold()
                scan.ext_counts[ext if ext in DOC_EXTS else "other"] += 1
                scan.total_files += 1
                try:
                    st = entry.stat(follow_symlinks=False)   # cached on Windows
                    scan.total_bytes += st.st_size
                    if scan.newest_mtime is None or st.st_mtime > scan.newest_mtime:
                        scan.newest_mtime = st.st_mtime
                except OSError:
                    pass                          # unreadable file — skip its stat only
                if ext in DOC_EXTS:
                    doc_names.append(entry.name)

            if doc_names:
                scan.twin_pairs += len(find_twin_pairs(doc_names))
                leaf = tree.setdefault(method_name, {}).setdefault(
                    year, {}).setdefault(client, {"count": 0, "sample": []})
                leaf["count"] += len(doc_names)
                room = file_cap - len(leaf["sample"])
                if room > 0:
                    leaf["sample"].extend(sorted(doc_names)[:room])
    except OSError as exc:
        # A mid-walk disconnect: keep whatever we gathered, flag it degraded.
        scan.error = f"partial scan — {type(exc).__name__}: {exc}"

    scan.ext_counts = dict(scan.ext_counts)           # freeze the defaultdict
    return scan


def _reachable_within(root: Path, timeout: float) -> bool | None:
    """Bounded reachability probe. ``True``/``False`` = answered; ``None`` = timed out.

    Only the cheap ``exists()``/``is_dir()`` handshake is bounded — the part that
    blocks on SMB session negotiation for a pingable-but-unshared host. The probe
    runs in a daemon worker thread; if it hasn't answered within ``timeout`` the
    root is treated as unreachable and the still-blocked call is abandoned (daemon
    threads never hold up interpreter exit).
    """
    box: dict[str, bool] = {}

    def _work() -> None:
        try:
            box["ok"] = root.exists() and root.is_dir()
        except OSError:
            box["ok"] = False

    worker = threading.Thread(target=_work, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive() or "ok" not in box:
        return None
    return box["ok"]


def scan_root_bounded(root: Path, raw_path: str, timeout: float | None,
                      file_cap: int = 15) -> RootScan:
    """Probe reachability under ``timeout``, then fully scan a reachable root.

    The tight bound guards ONLY the reachability handshake (see
    :func:`_reachable_within`), so a hung/offline host degrades to a recorded
    "timeout" fast. Once a root answers as reachable, the full read-only walk runs
    to completion WITHOUT the bound — a large but healthy share (thousands of files
    stat'd over SMB) is catalogued in full rather than truncated to "offline".
    ``timeout`` of ``None`` or ``<= 0`` disables the probe (tests scanning a local
    ``tmp_path`` tree with no network in play).
    """
    if timeout and timeout > 0:
        reachable = _reachable_within(root, timeout)
        if reachable is None:
            scan = RootScan(raw_path=raw_path, normalized=normalize_unc(raw_path))
            scan.reachable = False
            scan.error = (f"timeout after {timeout:.0f}s "
                          "(share offline / SMB not responding)")
            return scan
    # Reachable, unreachable-but-fast (False), or bound disabled: let scan_root
    # produce the real result — it reports a fast "path not found" itself.
    return scan_root(root, raw_path=raw_path, file_cap=file_cap)


def discover(lan_sources, file_cap: int = 15,
             timeout: float | None = DEFAULT_ROOT_TIMEOUT_S) -> DiscoveryResult:
    """Scan every configured source read-only; never raises and never hangs.

    Each root is bounded by ``timeout`` seconds (see :func:`scan_root_bounded`), so
    one unreachable share degrades to a recorded "timeout" instead of stalling the
    whole run. Pass ``timeout=None`` to disable the bound.
    """
    result = DiscoveryResult(generated_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    for raw in lan_sources or []:
        normalized = normalize_unc(raw)
        result.roots.append(scan_root_bounded(Path(normalized), str(raw),
                                              timeout, file_cap=file_cap))
    return result


# --- Reporting --------------------------------------------------------------------------


def _fmt_bytes(n: int) -> str:
    step = 1024.0
    val = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < step:
            return f"{val:.0f} {unit}" if unit == "B" else f"{val:.1f} {unit}"
        val /= step
    return f"{val:.1f} PB"


def _fmt_mtime(ts: float | None) -> str:
    if not ts:
        return "—"
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _sample_line(items, cap: int = 40) -> str:
    """Count + a capped representative sample for an edge-case list.

    A real share carries thousands of distinct folder names; dumping them all
    buries the report. Show the total and the first ``cap`` (sorted) with a
    ``+N more`` tail so the list stays scannable — full detail lives in the
    structure tree and ``--json`` dump.
    """
    items = list(items)
    if not items:
        return "_none detected_"
    shown = ", ".join(f"`{x}`" for x in items[:cap])
    extra = len(items) - cap
    total = f"**{len(items)}** distinct: "
    return total + shown + (f" … +{extra} more" if extra > 0 else "")


def render_markdown(result: DiscoveryResult) -> str:
    """Render the full discovery audit report as a Markdown string."""
    reachable = result.reachable_roots
    offline = [r for r in result.roots if not r.reachable]
    lines: list[str] = []
    ap = lines.append

    ap("# LAN Network Share — Discovery & Structure Mapping Report")
    ap("")
    ap(f"_Generated: {result.generated_at}. **Read-only scan** — no file on the "
       "share was written, moved or modified._")
    ap("")

    # --- Summary --------------------------------------------------------------
    ap("## 1. Summary")
    ap("")
    ap(f"- Configured source roots: **{len(result.roots)}** "
       f"(reachable: **{len(reachable)}**, unreachable: **{len(offline)}**)")
    ap(f"- Total files discovered: **{result.total_files}** "
       f"(`.docx`: **{result.total_docx}**, `.pdf`: **{result.total_pdf}**)")
    ap(f"- Twin `.pdf`/`.docx` pairs: **{result.total_twins}**")
    ap(f"- Total size: **{_fmt_bytes(result.total_bytes)}**")
    ap("")
    ap("| Network share (method root) | Reachable | Files | .docx | .pdf | Twins | "
       "Size | Newest file |")
    ap("|---|---|---:|---:|---:|---:|---:|---|")
    for r in result.roots:
        flag = "✅" if r.reachable else "❌ offline"
        label = r.normalized.rsplit("\\", 1)[-1] or r.normalized
        ap(f"| {label} | {flag} | {r.total_files} | {r.docx} | {r.pdf} | "
           f"{r.twin_pairs} | {_fmt_bytes(r.total_bytes)} | {_fmt_mtime(r.newest_mtime)} |")
    ap("")
    if offline:
        ap("> **Unreachable roots** (share offline / unmapped at scan time — rerun "
           "when connected):")
        for r in offline:
            ap(f"> - `{r.normalized}` — {r.error}")
        ap("")

    # --- Structure tree -------------------------------------------------------
    ap("## 2. Structure Tree (Method → Year → Client → Files)")
    ap("")
    if not any(r.tree for r in reachable):
        ap("_No structure mapped — every configured root was unreachable at scan "
           "time. Rerun the scanner while connected to the share._")
        ap("")
    for r in reachable:
        ap(f"### {r.normalized}")
        ap("")
        if not r.tree:
            ap("_(reachable, but no `.docx`/`.pdf` files found)_")
            ap("")
            continue
        ap("```")
        for method, years in sorted(r.tree.items()):
            ap(f"{method}/")
            for year, clients in sorted(years.items()):
                ap(f"  {year}/")
                for client, leaf in sorted(clients.items()):
                    ap(f"    {client}/  ({leaf['count']} files)")
                    for fn in leaf["sample"]:
                        ap(f"      - {fn}")
                    if leaf["count"] > len(leaf["sample"]):
                        ap(f"      … +{leaf['count'] - len(leaf['sample'])} more")
        ap("```")
        ap("")

    # --- Edge cases -----------------------------------------------------------
    ap("## 3. Identified Edge Cases")
    ap("")
    extras = sorted({f for r in reachable for f in r.extra_folders})
    clients = sorted({c for r in reachable for c in r.client_folders})
    years = sorted({y for r in reachable for y in r.year_folders})
    ap(f"- **Extra nested folders** (deeper than Method/Year/Client) — "
       f"{_sample_line(extras)}")
    ap(f"- **Year subfolders** — {_sample_line(years)}")
    ap(f"- **Client subfolders** — {_sample_line(clients)}")
    ap("- **Noisy prefixes / diacritics to normalise before staging**: method "
       "tokens like `PMI-`, client names with Turkish/Azerbaijani letters "
       "(`BOS-ŞELF`), combined vendor names (`UNIPER-PROKON`), and Cyrillic-bearing "
       "share names (`Ferrite content reports-2005-2026`). These must survive as "
       "UTF-8 through any staging copy.")
    ap("")

    # --- Staging strategy -----------------------------------------------------
    ap("## 4. Proposed Automated Staging Strategy (next phase)")
    ap("")
    ap("> This report is the **discovery** phase only. The staging below is a "
       "proposal for a later, separate change — nothing here copies anything yet.")
    ap("")
    ap("1. **Read-only copy, never move.** Stage from the share into local `input/` "
       "with a copy (preserving mtimes); the share is a source of truth and is never "
       "mutated. Skip files already staged (content hash) so reruns are idempotent.")
    ap("2. **De-duplicate twins.** For a stem present as both `.pdf` and `.docx`, "
       "prefer the `.docx` (already text). A lone `.pdf` is copied and then flows "
       "through the existing STAGE -1 converter (`pre_processor.convert_input_pdfs`).")
    ap("3. **Reuse the existing pipeline.** Once in `input/`, files are sorted and "
       "quarantined by the current `pre_processor` (`sort_input_files`, "
       "`discover_groups`) — no new sorting logic; the method/client vocabulary is "
       "the same `ndt_methods` / `clients` registry in `config/settings.yaml`.")
    ap("4. **Preserve provenance.** Record source UNC path + mtime alongside each "
       "staged file so a later audit can trace a local report back to its share "
       "origin without re-reading the network.")
    ap("")
    return "\n".join(lines) + "\n"


# --- CLI --------------------------------------------------------------------------------


def _result_to_dict(result: DiscoveryResult) -> dict:
    """Plain-dict view of a DiscoveryResult for --json (sets -> sorted lists)."""
    return {
        "generated_at": result.generated_at,
        "total_files": result.total_files,
        "total_docx": result.total_docx,
        "total_pdf": result.total_pdf,
        "total_twins": result.total_twins,
        "total_bytes": result.total_bytes,
        "roots": [
            {
                "raw_path": r.raw_path,
                "normalized": r.normalized,
                "reachable": r.reachable,
                "error": r.error,
                "total_files": r.total_files,
                "ext_counts": r.ext_counts,
                "total_bytes": r.total_bytes,
                "newest_mtime": r.newest_mtime,
                "year_folders": sorted(r.year_folders),
                "client_folders": sorted(r.client_folders),
                "extra_folders": sorted(r.extra_folders),
                "twin_pairs": r.twin_pairs,
            }
            for r in result.roots
        ],
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=("Read-only LAN network-share discovery scanner. Catalogs the "
                     "remote NDT report folders and writes " + REPORT_NAME + "."),
    )
    ap.add_argument("--json", action="store_true",
                    help="Also print the raw discovery result as JSON to stdout.")
    ap.add_argument("--report", metavar="PATH", default=None,
                    help=f"Override the report output path (default: ./{REPORT_NAME}).")
    return ap


def main(argv: list[str] | None = None) -> int:
    ns = _build_arg_parser().parse_args(argv)
    settings = load_settings(PROJECT_ROOT / "config" / "settings.yaml")
    lan_sources = (settings.raw.get("network_ingestion") or {}).get("lan_sources") or []

    if not lan_sources:
        print("No network_ingestion.lan_sources configured in settings.yaml — "
              "nothing to scan.")
        return 0

    result = discover(lan_sources)
    report_path = Path(ns.report) if ns.report else PROJECT_ROOT / REPORT_NAME
    report_path.write_text(render_markdown(result), encoding="utf-8")

    print("=" * 70)
    print("LAN network-share discovery complete (read-only).")
    print(f"  Roots scanned:  {len(result.roots)} "
          f"({len(result.reachable_roots)} reachable, "
          f"{len(result.roots) - len(result.reachable_roots)} offline)")
    print(f"  Files found:    {result.total_files} "
          f"(.docx {result.total_docx} / .pdf {result.total_pdf})")
    print(f"  Twin pairs:     {result.total_twins}")
    print(f"  Report written: {report_path}")
    print("=" * 70)

    if ns.json:
        print(json.dumps(_result_to_dict(result), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
