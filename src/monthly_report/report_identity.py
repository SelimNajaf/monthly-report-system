"""Report-number identity — parsing, normalising and comparing Report №s.

Cohesive home for every string rule about a report number: the retest-marker
grammar (``R1``/``RS1``/``RW``), the ASR/ARS exclusion test, comparison keys,
the SDLN leading-token filename cleaning, and the filename-authoritative
resolution of a document's Report №. Shared by the pre-processor, the
aggregator and the retest tracker so all stages agree on identity.

I/O contract
------------
resolve_report_no(meta, path) -> (report_no, discrepancy | None)
report_key(text) -> str            # comparison key
serial_year(report_no) -> int | None   # the -<YY>- year, expanded
leading_token(name) -> str         # clean SDLN filename token
"""

from __future__ import annotations

import re
from pathlib import Path

from . import docx_reader

# Trailing retest markers on a report number or weld id: R1, R2, RS1, RW, RW1,
# R1-1. NOTE: ``ASR``/``ARS`` are NOT retests here — they are excluded entirely
# (quarantined upstream), so they never reach retest ranking.
RETEST_SUFFIX = re.compile(r"(RS\d+|RW\d*|R\d+(?:-\d+)?)$", re.IGNORECASE)

# Documents whose filename or internal report number carry these substrings are
# excluded from all reports and quarantined (case-insensitive).
EXCLUDE_SUBSTRINGS = ("asr", "ars")

_LEADING_TOKEN = re.compile(r"[A-Za-z0-9-]+")

# The two-digit year every report number carries in its ``-<YY>-<seq>`` tail:
# ``MT-U-25-028`` -> 25, ``AZF-RT-W1-25-148`` -> 25. Anchored at the END of the
# number (after any retest marker is stripped), so the ``W1`` / ``U`` segments in
# the middle can never be mistaken for the year.
_SERIAL_YEAR = re.compile(r"-(\d{2})-\d{1,4}$")


def is_excluded(name: str, report_no: str) -> bool:
    """True if an ASR/ARS marker appears in the filename stem or report number."""
    hay = f"{name or ''} {report_no or ''}".casefold()
    return any(sub in hay for sub in EXCLUDE_SUBSTRINGS)


def squash(text: str) -> str:
    """Collapse internal whitespace/newlines to single spaces."""
    return re.sub(r"\s+", " ", (text or "").strip())


def strip_retest(token: str) -> str:
    """Remove a trailing retest marker (``KF-MT-26-005ASR`` -> ``KF-MT-26-005``)."""
    return RETEST_SUFFIX.sub("", token or "").strip()


def retest_rank(report_no: str) -> int:
    """0 = original; 1 = first retest (R1/RS1/RW); n = Rn (from the first digits)."""
    m = RETEST_SUFFIX.search(report_no or "")
    if not m:
        return 0
    digits = re.search(r"\d+", m.group(1))
    return int(digits.group()) if digits else 1   # RW (no digit) -> first retest


def serial_year(report_no: str) -> int | None:
    """The 4-digit inspection year encoded in a report number, or ``None``.

    ``MT-U-25-028`` -> 2025, ``U-UT-26-081R1`` -> 2026. The two digits are expanded
    as ``2000 + YY``: every report in this corpus is 21st-century, and a report
    number carries no century of its own, so there is nothing else it could mean.

    Used by :func:`date_detector.parse_inspection_date` to repair a date cell whose
    year was truncated by the inspector ("17.03.202"). It is deliberately the LAST
    ``-NN-`` group: a hypothetical four-segment number like ``MPI-25-01-5`` would
    read its year as ``01`` rather than ``25``. That shape does not occur here —
    every one of the corpus's report numbers ends ``-<YY>-<seq>`` — but a future
    numbering scheme with a trailing sub-index would need this rule revisited.
    """
    m = _SERIAL_YEAR.search(strip_retest(report_no or ""))
    return 2000 + int(m.group(1)) if m else None


def norm_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def report_key(text: str) -> str:
    """Comparison key for report numbers: upper-case, strip spaces/underscores."""
    return re.sub(r"[\s_]+", "", (text or "").strip()).upper()


def leading_token(name: str) -> str:
    """The leading report-number token of a filename stem (see :func:`report_key_of`)."""
    stem = Path(name).stem
    stem = re.sub(r"(_en)+$", "", stem, flags=re.IGNORECASE).strip()
    m = _LEADING_TOKEN.match(stem)
    return m.group(0) if m else stem


def report_key_of(name: str) -> str:
    """Comparison key for a report file: its **leading** report-number token.

    The token stops at the first space or underscore, which strips the job/date
    noise the SDLN exports carry. That is the point — a whole-stem key would miss
    real twins::

        U-UT-26-001  (Platform).pdf          -> U-UT-26-001
        U-UT-26-001  (Platform)_en_en.docx   -> U-UT-26-001   (same report)
        U-UTM-26-001_______F1945___.pdf      -> U-UTM-26-001
        U-UTM-26-001.docx                    -> U-UTM-26-001  (same report)

    Normalised through :func:`report_key` so casing/spacing never splits a pair.
    """
    return report_key(leading_token(name))


#: Tails a report-number filename may legitimately carry after its leading token.
#: A parenthesised job/standard group is already stripped by
#: :func:`docx_reader.parse_filename_metadata`; a retest marker is part of the
#: number itself. Anything else is corpus noise.
_DOC_SUFFIXES = (".docx", ".doc", ".pdf")


def identity_noise(name: str | Path) -> str | None:
    """Why a filename's Report № is not its leading token — or ``None`` when clean.

    The filename is authoritative (:func:`resolve_report_no`), so whatever noise it
    carries ships into the monthly document as the report number. This function
    **reports** that noise; it never removes it. Cleaning would mean guessing which
    half of ``UT-U-25-003 rej`` is the number, and the corpus proves the guess would
    be wrong — ``U-UT-25-003rej`` is a real report number whose ``rej`` belongs to it.

    Returns a short Azerbaijani reason (``ikiqat uzantı`` / ``ardıcıl alt-xətt`` /
    ``naməlum şəkilçi``) for the audit, so the operator fixes the *file name* — the
    only place the fix belongs.
    """
    fn = docx_reader.parse_filename_metadata(name)
    filename_no = squash(fn.get("report_no") or "").replace(" ", "")
    token = leading_token(name)
    if not token or report_key(filename_no) == report_key(token):
        return None
    tail = filename_no[len(token):].strip() if filename_no.startswith(token) else filename_no
    if not tail or RETEST_SUFFIX.fullmatch(tail):
        return None
    if tail.casefold().startswith(_DOC_SUFFIXES):
        return "ikiqat uzantı"
    if "__" in tail:
        return "ardıcıl alt-xətt"
    return "naməlum şəkilçi"


def resolve_report_no(meta: dict, path) -> tuple[str, tuple[str, str] | None]:
    """Resolve a report's authoritative number and flag filename↔internal drift.

    The filename is authoritative (inspectors sometimes mistype the in-document
    ``Report No:`` field), so on a mismatch the filename value wins. Returns
    ``(report_no, discrepancy)`` where ``discrepancy`` is ``(filename_no,
    internal_no)`` when both are present and differ, else ``None``. When one side
    is missing the other is used silently.
    """
    fn = docx_reader.parse_filename_metadata(path)
    filename_no = squash(fn.get("report_no") or "").replace(" ", "")
    internal_no = squash(meta.get("report_no", "")).replace(" ", "")
    if filename_no and internal_no and report_key(filename_no) != report_key(internal_no):
        return filename_no, (filename_no, internal_no)
    return (filename_no or internal_no or squash(Path(path).stem).replace(" ", "")), None
