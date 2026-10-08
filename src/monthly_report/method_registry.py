"""Config-driven method & client registry — detection and resolution.

NO method token is hardcoded. The recognised report-number tokens (MT, UT, DP,
PMI, FC, UTM, HrT, ...) are derived from the ``ndt_methods`` registry patterns
in settings.yaml, so onboarding a method is a pure-config change. The compiled
regexes + lookup maps are memoized per settings object (keyed by the raw dict's
identity) so the whole batch shares one compilation.

Also home to the ``clients`` registry lookups (prefixes, aliases, VÖEN) and the
filename-sorting registry used by the pre-processor.

I/O contract
------------
detect_method(report_no, settings) -> str
resolve_client_by_field(meta, report_no, settings) -> (code, name)
client_voen(code, settings) -> str
compile_sort_registry(settings) -> [(code, folder, regex), ...]
"""

from __future__ import annotations

import re
from pathlib import Path

from . import date_detector, extractor, pdf_twin
from .report_identity import is_excluded, resolve_report_no, squash
from .text_norm import fold_typography

_DETECT_CACHE: dict = {}


def _registry_detect(settings):
    """Return ``(tokens, method_re, client_re, method_first_re, folder_map, informational)``.

    * ``tokens`` — uppercased alpha tokens from every registry pattern, longest
      first (so ``UTM`` is tried before ``UT``, ``UTR`` before ``UT``).
    * ``method_re`` — matches a whole hyphen/boundary-delimited token in a report
      number.
    * ``client_re`` — captures the client prefix before ``-<TOKEN>-``.
    * ``method_first_re`` — captures the client token that sits AFTER the method in
      a method-first report number (``UT-SDLN-26-042`` -> ``SDLN``). Used only as a
      fallback when ``client_re`` misses (no prefix before the method).
    * ``folder_map`` — token -> output/input folder (``FC`` -> ``FERRITE``,
      ``MT`` -> ``MPI``, ...).
    * ``informational`` — set of tokens whose method is marked informational.
    """
    key = id(settings.raw)
    cached = _DETECT_CACHE.get(key)
    if cached is not None:
        return cached
    registry = settings.raw.get("ndt_methods", {}) or {}
    tokens: set[str] = set()
    folder_map: dict[str, str] = {}
    informational: set[str] = set()
    for code, spec in registry.items():
        spec = spec or {}
        folder = str(spec.get("folder", code))
        info = bool(spec.get("informational", False))
        for pat in (spec.get("patterns") or []):
            tok = re.sub(r"[^A-Za-z]", "", str(pat)).upper()
            if not tok:
                continue
            tokens.add(tok)
            folder_map.setdefault(tok, folder)   # first registry entry wins
            if info:
                informational.add(tok)
    toks_sorted = sorted(tokens, key=len, reverse=True)
    alt = "|".join(re.escape(t) for t in toks_sorted) or r"(?!x)x"
    method_re = re.compile(rf"(?<![A-Za-z])({alt})(?![A-Za-z])", re.IGNORECASE)
    client_re = re.compile(rf"^(.+?)-(?:{alt})-", re.IGNORECASE)
    method_first_re = re.compile(rf"^(?:{alt})-([A-Za-z]+)-", re.IGNORECASE)
    result = (toks_sorted, method_re, client_re, method_first_re, folder_map,
              informational)
    _DETECT_CACHE[key] = result
    return result


def detect_method(report_no: str, settings) -> str:
    """Classify a report by inspection method token from its report number.

    ``KF-MT-26-001`` -> ``MT``; ``U-UT-26-010`` -> ``UT``; ``KF-FC-26-001`` ->
    ``FC``; ``U-UTM-26-001`` -> ``UTM``. The token set is config-driven (see
    :func:`_registry_detect`). Returns ``"NDT"`` when no registered token matches.
    """
    method_re = _registry_detect(settings)[1]
    m = method_re.search(report_no or "")
    return m.group(1).upper() if m else "NDT"


def detect_client(report_no: str, settings) -> str:
    """Return the client code of a report number.

    Primary form — client PREFIX before the method token:
    ``AZF-RT-W1-26-304`` -> ``AZF``; ``U-UT-26-010`` -> ``U``;
    ``KF-DP-26-001`` -> ``KF``.
    Fallback — method-first names carry the client token AFTER the method, so when
    the prefix form misses we read the segment after the method:
    ``UT-SDLN-26-042`` -> ``SDLN``; ``RT-SDLN-26-698`` -> ``SDLN``.
    Returns ``""`` when neither form matches (e.g. ``MT-26-001``).
    """
    _t, _m, client_re, method_first_re, _f, _i = _registry_detect(settings)
    rn = (report_no or "").strip()
    m = client_re.match(rn)
    if m:
        return m.group(1).strip().upper()
    m = method_first_re.match(rn)
    return m.group(1).strip().upper() if m else ""


def method_folder(method: str, settings) -> str:
    """Map a method token to its input/output folder (``FC`` -> ``FERRITE``).

    Falls back to the uppercased token itself when it is unregistered.
    """
    folder_map = _registry_detect(settings)[4]
    tok = (method or "").upper()
    return folder_map.get(tok, tok)


def is_informational(method: str, settings) -> bool:
    """True when the method token belongs to an ``informational: true`` entry.

    Informational methods (UTM, HrT) always report ``"Məlumat üçün"`` — no
    Yararlı/Yarasız verdict is computed.
    """
    *_rest, informational = _registry_detect(settings)
    return (method or "").upper() in informational


def is_excluded_client(code: str, settings) -> bool:
    """True when a client code is on the ``excluded_clients`` list in settings.yaml.

    Retired accounts (SIENMAR, Qafqaz Trans Service) stay in the ``clients``
    registry so their documents can still be RECOGNISED — this is what then keeps
    them out of every compiled report. Config-driven, like every other exclusion:
    retiring a client is a settings edit, not a code change.
    """
    excluded = settings.raw.get("excluded_clients") or []
    target = (code or "").strip().casefold()
    if not target:
        return False
    return any(target == str(c).strip().casefold() for c in excluded)


def is_active_client(code: str, settings) -> bool:
    """False only when the client's ``clients`` entry sets ``active: false``.

    The inline, preferred way to retire a client (the companion to the legacy
    ``excluded_clients`` list — either signal retires an account, and both are
    honoured everywhere the blacklist bites). A client with no entry, or an entry
    with no ``active`` key, is active by default, so onboarding a new client never
    needs the flag. Resolved by registry ``code`` (falling back to the registry
    key), like :func:`client_voen`.
    """
    registry = settings.raw.get("clients", {}) or {}
    target = (code or "").strip().casefold()
    if not target:
        return True
    for key, spec in registry.items():
        spec = spec or {}
        if str(spec.get("code", key)).strip().casefold() == target:
            return bool(spec.get("active", True))
    return True   # unregistered client: active by default


def is_approved_client(code: str, settings) -> bool:
    """True when a client code is on the ``approved_clients`` allowlist.

    The STRICT companion to the denylist rules (:func:`is_active_client`,
    :func:`is_excluded_client`): where those default to allow (a client with no
    ``active: false`` and no ``excluded_clients`` entry passes, and so does an
    unregistered code), this defaults to allow ONLY while the allowlist is empty.
    Once ``approved_clients`` names any code, every other code — including an
    unregistered one that would slip past the denylist — is refused. That is what
    makes an upload target list "strict": the set of clients that may be filed is
    the config's, not "everything not yet retired".

    Empty / absent ``approved_clients`` returns True for every code, so the
    allowlist is opt-in and off by default (mirroring how an empty
    ``excluded_clients`` excludes nothing). A blank code returns True — deciding
    whether to *consider* an unreadable sidecar is not this gate's job. Matched by
    casefolded registry ``code``, like :func:`is_active_client`.
    """
    approved = settings.raw.get("approved_clients") or []
    if not approved:
        return True
    target = (code or "").strip().casefold()
    if not target:
        return True
    return any(target == str(c).strip().casefold() for c in approved)


def volume_threshold(method: str, settings) -> tuple[int, int]:
    """The ``(min_reports, min_items)`` volume floor for a method.

    Config-driven, like every other registry: reads ``volume_thresholds`` from
    settings.yaml, taking a per-method entry keyed by the upper-cased token and
    falling back to the ``default`` entry. A missing block / missing keys give
    ``(0, 0)`` — i.e. no floor — mirroring how an empty ``excluded_clients``
    excludes nothing.
    """
    block = settings.raw.get("volume_thresholds") or {}
    default = block.get("default") or {}
    entry = block.get((method or "").upper()) or {}
    min_reports = int(entry.get("min_reports", default.get("min_reports", 0)) or 0)
    min_items = int(entry.get("min_items", default.get("min_items", 0)) or 0)
    return min_reports, min_items


def meets_volume(method: str, reports: int, items: int, settings) -> bool:
    """True when a group is big enough to compile/upload under its method's floor.

    OR gate: only POSITIVE thresholds are active, and a group passes when it clears
    ANY active one — it is skipped only when it fails EVERY active threshold. A
    dimension set to 0 is off, so an all-zero entry (the shipped default) never
    skips anything: the whole feature is opt-in. To gate on items alone, leave
    ``min_reports`` 0 and set ``min_items`` > 0 (and vice-versa).
    """
    min_reports, min_items = volume_threshold(method, settings)
    checks = []
    if min_reports > 0:
        checks.append(reports >= min_reports)
    if min_items > 0:
        checks.append(items >= min_items)
    return (not checks) or any(checks)


def min_total_client_volume(settings) -> int:
    """The corpus-wide minimum cumulative report count per client, from settings.

    Reads ``filtering.min_total_client_volume``; ``0`` (or a missing block/key)
    turns the whole corpus-volume filter OFF — every active client compiles —
    mirroring how an empty ``excluded_clients`` excludes nobody.
    """
    block = settings.raw.get("filtering") or {}
    return int(block.get("min_total_client_volume", 0) or 0)


def corpus_client_stats(items, settings) -> dict[str, tuple[int, set[str]]]:
    """Cumulative ``{code: (report_count, {months})}`` across the WHOLE corpus.

    ``items`` is any iterable of ``(Path, tables)`` — the shared parse cache, which
    holds every ``.docx`` under ``input/`` (the full history, since cross-month
    retest linking keeps old files on disk). This is the "cumulative document counts
    per client across the full input/ tree" the corpus-volume rule needs: a client's
    volume is judged over ALL months at once, not one isolated month, so 1 report in
    month A plus 10 in month B counts as 11.

    ASR/ARS files (:func:`is_excluded`) and unreadable entries are skipped — they
    never compile, so they must not pad a client's volume. Each remaining file
    contributes 1 to its resolved client's count and its inspection month (``YYYY-MM``,
    when datable) to that client's month set.
    """
    stats: dict[str, tuple[int, set[str]]] = {}
    for path, tables in items:
        if isinstance(tables, Exception):
            continue
        meta = extractor.extract_meta(tables)
        report_no, _drift = resolve_report_no(meta, path)
        if is_excluded(path.name, report_no):
            continue
        code, _name = resolve_client_by_field(meta, report_no, settings)
        # report_no is passed so a truncated-year cell resolves to the same month
        # here as it does in discover_groups; a client's month set must not depend
        # on which stage looked at it.
        date = date_detector.parse_inspection_date(
            meta.get("date", ""), settings.dayfirst, report_no,
            pdf_twin.names_for(path, settings))
        count, months = stats.get(code, (0, set()))
        months = set(months)
        if date is not None:
            months.add(f"{date.year:04d}-{date.month:02d}")
        stats[code] = (count + 1, months)
    return stats


def client_volume_ok(code: str, stats: dict, settings) -> bool:
    """True when a client clears the corpus-wide cumulative volume rule.

    Kept (True) when the filter is off (``min_total_client_volume <= 0``), OR the
    client's reports span **>= 2 distinct months** (recurring — kept regardless of
    count), OR the cumulative count meets the floor. A single-month client below the
    floor is a throwaway one-off and fails here (skipped in place — its files stay in
    ``input/`` so a later month can push it over). ``code`` absent from ``stats`` is
    treated as ``(0, {})`` and fails whenever the floor is positive.
    """
    floor = min_total_client_volume(settings)
    if floor <= 0:
        return True
    count, months = stats.get(code, (0, set()))
    return len(months) >= 2 or count >= floor


def is_admitted_client(code: str, stats: dict, settings) -> bool:
    """True when a client may compile: active, not blacklisted, clears volume.

    Convenience predicate combining the retire rules (:func:`is_active_client`,
    :func:`is_excluded_client`) with the corpus-volume rule
    (:func:`client_volume_ok`). Used where all three must hold at once.
    """
    return (is_active_client(code, settings)
            and not is_excluded_client(code, settings)
            and client_volume_ok(code, stats, settings))


def is_uploadable_client(code: str, settings) -> bool:
    """True when a client may be FILED on the live portal — the upload-side gate.

    The upload counterpart to :func:`is_admitted_client` (the compilation gate,
    which deliberately omits the allowlist because a client can be perfectly
    compilable and still not be cleared to reach a government form). Combines the
    retire rules with the strict ``approved_clients`` allowlist, so every uploader
    entry point asks ONE question instead of re-assembling three.

    Blank codes are where this differs from :func:`is_approved_client`, whose job
    stops at the list itself. Here the sidecar has already been consulted, so an
    unresolved client is a decision:

    * allowlist NON-EMPTY -> a blank code is REFUSED (fail closed). The operator
      asked for exactly N clients; a report whose client cannot be read is not one
      of them, and guessing on a live filing is the one mistake with no undo.
    * allowlist empty / absent -> the allowlist is off, so this degrades to the
      retire rules alone and a blank code passes, exactly as before.
    """
    approved = settings.raw.get("approved_clients") or []
    if not (code or "").strip():
        return not approved
    return (is_active_client(code, settings)
            and not is_excluded_client(code, settings)
            and is_approved_client(code, settings))


def _standard_key(value: str) -> str:
    """Separator-blind, case-folded key: runs of space/hyphen/underscore -> one space.

    So ``"ISO-17636"``, ``"ISO 17636"`` and ``"iso  17636"`` collapse to the same
    key. Used both to compare literal allowlist entries and to normalize a
    candidate before a regex full-match.

    Typography is folded first (:func:`text_norm.fold_typography`), so a Word-dashed
    ``"EP‐GIS‐18‐016"`` (U+2010) keys the same as the ASCII spelling an operator
    would type into ``allowed_standards``. Without that, adding the ASCII form to the
    allowlist leaves the U+2010 rows quarantined and gives no clue why.
    """
    return re.sub(r"[\s_-]+", " ", fold_typography(value).strip()).casefold()


def is_allowed_standard(std: str, settings) -> bool:
    """True when a document's NDT standard is on the ``allowed_standards`` allowlist.

    Config-driven, like every other ingestion filter. Rules:

    * A blank/unextractable ``std`` is allowed — the guardrail only rejects a
      standard it can positively read and disprove; blanks are left to the
      sibling/method-default fallback in :mod:`document_aggregator`.
    * A missing/empty ``allowed_standards`` list allows everything (feature off),
      mirroring how an empty ``excluded_clients`` excludes nothing.
    * A list entry that starts with ``^``, ends with ``$``, or contains a backslash
      is a REGEX: it is full-matched (case-insensitive) against the candidate with
      typography folded and separators normalized to single spaces, so
      ``^ASME\\s+…$`` matches ``"ASME VIII"``, ``"ASME-VIII"`` and ``"ASME–VIII"``.
    * Any other entry is a LITERAL: separator-blind, case-insensitive equality.
    """
    if not (std or "").strip():
        return True
    allowed = settings.raw.get("allowed_standards") or []
    if not allowed:
        return True
    key = _standard_key(std)
    normalized = re.sub(r"[\s_-]+", " ", fold_typography(std).strip())
    for entry in allowed:
        entry = str(entry)
        if entry.startswith("^") or entry.endswith("$") or "\\" in entry:
            if re.fullmatch(entry, normalized, re.IGNORECASE):
                return True
        elif _standard_key(entry) == key:
            return True
    return False


#: Trailing edition/section/revision noise on a body ACC-Standard cell — the tail
#: past the normative token. ``"EEMUA 158 Edition 3 Section 7.5.4"`` -> cut at
#: ``Edition``. Anchored on a word boundary so it never bites a standard name.
_STD_TAIL = re.compile(r"\b(edition|ed|section|sec|table|tbl|rev|revision|doc|part|"
                       r"clause|para|paragraph|criteria|appendix|annex)\b.*",
                       re.IGNORECASE)


def _standard_head(std: str) -> str:
    """Reduce a noisy body standard to its leading normative token.

    The in-body ``ACC Standard`` cell carries edition/section suffixes and
    doc-refs (``"EEMUA 158,Edition 3,Section 7.5.4"``, ``"ISO 17636 Table 5"``)
    that a clean filename standard never has. This strips that tail: cut at the
    first ``,`` / ``(`` / ``;`` / newline, then drop a trailing
    edition/section/revision phrase. ``/`` is deliberately NOT a cut point —
    ``ASTM E797/E797M`` and ``EEMUA 153/158`` are single normative names.
    """
    head = re.split(r"[,(;\n]", std or "", maxsplit=1)[0]
    head = _STD_TAIL.sub("", head)
    return head.strip()


#: Delimiters that separate two DISTINCT standards inside one ``ACC Standard`` cell.
#:
#: **Kept byte-identical to ``uploader._STANDARD_ITEM_SPLIT``** — the same cell text is
#: split twice on two sides of the pipeline (here, to decide whether a row compiles at
#: all; there, to decide which portal options an appeal names), and a difference between
#: the two would mean a row that compiles cannot be filed, or the reverse. The two are
#: deliberately NOT shared by import: the uploader's standard-matching path is frozen,
#: so the constant is copied and ``tests/test_composite_standards.py`` asserts the copies
#: are equal, turning a silent drift into a failing test.
#:
#: Comma, slash and plus split ONLY when whitespace flanks them, because all three also
#: occur INSIDE a single name or suffix ("EEMUA 153/158", "ASTM E797/E797M",
#: "EEMUA 158,Edition 3,Section 7.5.4"). Semicolon, "&" and the word "and" never occur
#: mid-name, so they split unconditionally.
_STANDARD_ITEM_SPLIT = (
    r"\s*;\s*"          # semicolon
    r"|\s*&\s*"         # ampersand
    r"|\s+and\s+"       # the English word 'and'
    r"|\s+/\s*|/\s+"    # slash flanked by whitespace on at least one side
    r"|\s+,\s*|,\s+"    # comma flanked by whitespace on at least one side
    r"|\s+\+\s*|\+\s+"  # plus flanked by whitespace on at least one side
)


def split_standard_parts(std: str) -> list[str]:
    """Split a composite ``ACC Standard`` cell into its individual standards.

    ``"API 1104 & ASME IX"`` -> ``["API 1104", "ASME IX"]``; a lone standard returns
    ``[itself]``. A part carrying no letter and no digit is dropped: a cell left as a
    bare ``"+"`` names no document, and returning it would refuse a report over a
    punctuation mark.
    """
    text = fold_typography(std or "").strip()
    if not text:
        return []
    return [tok.strip()
            for tok in re.split(_STANDARD_ITEM_SPLIT, text, flags=re.IGNORECASE)
            if tok and any(c.isalnum() for c in tok)]


def _allowed_whole_or_head(std: str, settings) -> bool:
    """The strict check, retried on the leading normative token (:func:`_standard_head`)."""
    if is_allowed_standard(std, settings):
        return True
    head = _standard_head(std)
    if head and head != (std or "").strip():
        return is_allowed_standard(head, settings)
    return False


def is_allowed_standard_lenient(std: str, settings) -> bool:
    """Allowlist check that tolerates edition/section noise and composite cells.

    Three ordered attempts, each narrower than the last:

    1. **The whole string, strictly** (:func:`is_allowed_standard`) — blank, literal
       and regex entries all pass here. This runs FIRST for a reason: an approved
       literal may itself contain a separator (``"Sec 11, Q02412 Rev C"``), and
       splitting before matching would tear such an entry into halves that are on no
       list. Whole-first makes the allowlist, not the splitter, the authority.
    2. **The leading normative token** (:func:`_standard_head`) — an approved norm
       carrying an edition/section suffix (``"EEMUA 158,Edition 3,Section 7.5.4"``,
       ``"ISO 17636 Table 5"``) is ALLOWED on its head.
    3. **Composite split** (:func:`split_standard_parts`) — a cell naming two documents
       (``"API 1104 & ASME IX"``) passes only when EVERY part passes step 1 or 2.
       There is no partial pass: a row whose cell half-names an unapproved document was
       assessed against that document too, and compiling it would put a norm in the
       state's report that nobody approved. This mirrors the uploader's rule, where one
       unoffered part refuses the whole appeal.

    A genuinely foreign code (``"EP-GIS-42-103"``) or an unapproved doc-ref pair
    (``"GIS-42-103 / 341.4"`` — both halves unlisted) is still REJECTED at every step.

    Used at the :mod:`document_aggregator` ingestion gate, where the resolved standard
    may be the noisy body cell rather than the clean filename. :func:`is_allowed_standard`
    itself is deliberately NOT widened, so the filename-standard quarantine brake in
    :mod:`pre_processor` keeps its strict behaviour.
    """
    if _allowed_whole_or_head(std, settings):
        return True
    parts = split_standard_parts(std)
    if len(parts) < 2:
        return False
    return all(_allowed_whole_or_head(part, settings) for part in parts)


def master_standards(md_path) -> list[str]:
    """Parse the authoritative master-standards Markdown table.

    ``standarts/butun_standartlar.md`` is the company's canonical list of
    approved NDT norms, a two-column table (``№ | Standart``). This returns the
    ``Standart`` cell of every DATA row, in file order — the header, the
    ``|---|`` separator row and any non-table line are skipped. It is the seam
    that ties the enforced ``allowed_standards`` allowlist back to the master
    document: ``tests/test_master_standards_sync.py`` asserts every name this
    yields is :func:`is_allowed_standard`, so the two can never silently drift.
    """
    out: list[str] = []
    for line in Path(md_path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        num, std = cells[0], cells[1]
        if not num.isdigit():          # header ("№") and |---| separator rows
            continue
        if std:
            out.append(std)
    return out


def _client_registry(settings) -> dict[str, tuple[str, str]]:
    """Build ``{PREFIX: (code, name)}`` from the config ``clients`` registry."""
    out: dict[str, tuple[str, str]] = {}
    registry = settings.raw.get("clients", {}) or {}
    for key, spec in registry.items():
        spec = spec or {}
        code = str(spec.get("code", key))
        name = str(spec.get("name", code))
        for pref in (spec.get("prefixes") or [key]):
            out[str(pref).strip().upper()] = (code, name)
    return out


def resolve_client(report_no: str, settings) -> tuple[str, str]:
    """Resolve a report's ``(client_code, client_name)`` from its prefix.

    Uses the config ``clients`` registry; an unmapped prefix falls back to
    ``(prefix, prefix)`` so new clients still compile, and a prefix-less number
    falls back to ``("NA", "NA")``.
    """
    prefix = detect_client(report_no, settings)
    if not prefix:
        return "NA", "NA"
    return _client_registry(settings).get(prefix, (prefix, prefix))


def client_voen(code: str, settings) -> str:
    """Return a client's VÖEN (Tax ID) from the config ``clients`` registry.

    Looks the resolved ``code`` up against each registry entry's ``code`` (falling
    back to the registry key) and returns its ``voen`` string. Returns ``""`` when
    the client is unregistered or has no configured VÖEN, so an unmapped client
    never crashes the JSON export — it just carries an empty identifier.
    """
    registry = settings.raw.get("clients", {}) or {}
    for key, spec in registry.items():
        spec = spec or {}
        if str(spec.get("code", key)) == code:
            return str(spec.get("voen", ""))
    return ""


def _client_alias_index(settings) -> list[tuple[str, str, str]]:
    """Build ``[(alias, code, name), ...]`` from the config ``clients`` registry.

    Aliases are lower-cased and registry order is preserved so the first entry with
    a matching alias wins. Used to resolve a client from the document's internal
    ``Client:`` field (whitespace-normalized substring match).
    """
    out: list[tuple[str, str, str]] = []
    registry = settings.raw.get("clients", {}) or {}
    for key, spec in registry.items():
        spec = spec or {}
        code = str(spec.get("code", key))
        name = str(spec.get("name", code))
        for alias in (spec.get("aliases") or []):
            a = squash(str(alias)).lower()
            if a:
                out.append((a, code, name))
    return out


def resolve_client_by_field(meta: dict, report_no: str, settings) -> tuple[str, str]:
    """Resolve ``(client_code, client_name)`` INTERNALLY-FIRST, prefix as fallback.

    The document body's ``Client:`` field is authoritative: it is whitespace-
    normalized and matched (case-insensitive substring) against each registry
    entry's ``aliases`` — so two clients sharing a report-number prefix (Khazar
    Fabrication vs Khazar Engineering, both ``KF``) are correctly separated, and a
    mojibaked value still matches on its surviving token (``qafqaz``, ``nov``). When
    the field is empty or matches no alias, fall back to the prefix-based
    :func:`resolve_client` so every document still lands in a sensible group.
    """
    field = squash(meta.get("client", "")).lower()
    if field:
        for alias, code, name in _client_alias_index(settings):
            if alias in field:
                return code, name
    return resolve_client(report_no, settings)


def method_default_standard(settings, method: str) -> str:
    """Config-mapped last-resort acceptance standard for a method token.

    Reads ``ndt_methods[*].default_standard`` for the registry entry whose
    ``patterns`` carry the exact hyphen-delimited method token (``"-MT-"`` ->
    the MPI entry, so ``MT`` resolves the MPI default). Returns ``""`` when the
    method is unregistered or has no configured default.
    """
    needle = f"-{(method or '').strip()}-".casefold()
    registry = settings.raw.get("ndt_methods", {}) or {}
    for _code, spec in registry.items():
        spec = spec or {}
        patterns = [str(p).casefold() for p in (spec.get("patterns") or [])]
        if needle in patterns and str(spec.get("default_standard", "")).strip():
            return str(spec["default_standard"]).strip()
    return ""


def compile_sort_registry(settings) -> list[tuple[str, str, "re.Pattern[str]"]]:
    """Compile the config ndt_methods registry into (code, folder, regex) tuples.

    Patterns are matched case-insensitively against the filename. Registry order
    is preserved so more specific methods (e.g. UTR) are tried before broader ones
    (UT). Invalid regex in one pattern is skipped, not fatal (per graceful
    degradation): a bad entry never blocks sorting of the rest.
    """
    compiled: list[tuple[str, str, "re.Pattern[str]"]] = []
    registry = settings.raw.get("ndt_methods", {}) or {}
    for code, spec in registry.items():
        spec = spec or {}
        folder = str(spec.get("folder", code))
        for pat in spec.get("patterns", []) or []:
            try:
                compiled.append((code, folder, re.compile(str(pat), re.IGNORECASE)))
            except re.error as exc:
                print(f"  [registry] bad pattern {pat!r} for {code}: {exc}")
    return compiled
