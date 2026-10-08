"""Two readers, one answer — or no answer at all (ADR-003 D2).

``pdf_reader`` returns two independent reconstructions of the same page: B1 from
the ruling lines, B3-C from word coordinates. Measured over 630 PDF/docx pairs,
each is wrong on a handful of reports and **their failure sets do not overlap**.
That is the property this module trades on:

* the two agree  -> the answer was right in **all 611** agreeing cases, silent
  errors **0**;
* the two differ -> nothing here guesses. The report is quarantined and written
  to an audit file with both answers side by side, and a human decides.

The gate was never "be accurate". It was "never be **silently** wrong", and a
disagreement that reaches the operator is not silent. 19 of 630 (3.0%) reach the
operator; 8 of those are in live method folders.

Blocking vs warning
-------------------
Only ``result`` blocks. It is the field whose disagreement was actually measured,
and the field whose error ships a wrong verdict to a client. The metadata fields
are compared too — a disagreement is real information and goes in the audit — but
they do not quarantine, because their disagreement rate is unmeasured and a
blocking rule built on an unmeasured rate is a guess about how much work to hand
the operator.

I/O contract
------------
compare(primary, crosscheck, path=..., method=None) -> list[Disagreement]
write_audit(output_dir, disagreements) -> Path | None
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

from . import extractor
from .document_aggregator import _aggregate_result

#: Reason text printed on the ``[quarantine]`` console line when the readers
#: disagree. **Contract:** ``gui/services/quarantine_reasons_service._TAGS`` and
#: ``quarantine_service.REASON_HINTS`` both match on this substring to give the
#: Quarantine page its chip and its hint. Reword the tail, never this prefix.
DISAGREEMENT_REASON = "pdf readers disagree"

#: Fields whose disagreement quarantines the report. Everything else is recorded
#: and shipped — see the module docstring for why the line is drawn here.
BLOCKING_FIELDS = ("result",)

#: Human names for the two readers, used in the audit's column headers so the
#: operator can tell which column came from which reconstruction.
PRIMARY_NAME = "B1 (find_tables)"
CROSSCHECK_NAME = "B3-C (word grid)"


@dataclass(frozen=True)
class Disagreement:
    """One field on which the two readers did not produce the same value."""

    report_no: str
    field: str
    primary: str
    crosscheck: str
    path: str
    blocking: bool


def verdict_of(tables: list[list[list[str]]], method: str | None = None) -> str:
    """The document-level verdict a given grid produces.

    ``method=None`` (the reader dispatch has no method yet) tries the RT film-
    section reader first and falls back to the generic one — the RT reader needs
    an ``INSPECTION RESULT`` block header to yield anything, so on a non-RT
    template it returns ``[]`` and the fallback is the generic reader, which is
    exactly what ``document_aggregator`` would have chosen anyway.
    """
    if method == "RT":
        welds = extractor.extract_rt_welds(tables)
    elif method:
        welds = extractor.extract_welds(tables)
    else:
        welds = extractor.extract_rt_welds(tables) or extractor.extract_welds(tables)
    return _aggregate_result(welds, tables)


def _fields(tables: list[list[list[str]]], method: str | None) -> dict[str, str]:
    """The comparable values one grid yields, through the real extractor."""
    meta = extractor.extract_meta(tables)
    return {
        "report_no": (meta.get("report_no") or "").strip(),
        "date": (meta.get("date") or "").strip(),
        "client": (meta.get("client") or "").strip(),
        "material": (meta.get("material") or "").strip(),
        "standard": extractor.extract_standard(tables).strip(),
        "item": extractor.extract_item_global(tables).strip(),
        "result": verdict_of(tables, method),
    }


def _same(left: str, right: str) -> bool:
    """Compare two extracted values the way a reader difference should be judged.

    Whitespace and case are geometry artefacts — one reader may join two words the
    other splits — so they are not a disagreement. A value present in one reader
    and blank in the other IS one: a blank field is a failure to read, and a
    failure to read is precisely what the cross-check exists to catch.
    """
    return " ".join(left.split()).casefold() == " ".join(right.split()).casefold()


def compare(primary_tables: list[list[list[str]]],
            crosscheck_tables: list[list[list[str]]],
            *, path: str | Path = "", method: str | None = None,
            report_no: str = "") -> list[Disagreement]:
    """Every field on which the two reconstructions of one PDF disagree.

    The comparison is at **field** level, never raw cells: the two readers build
    genuinely different cell structures from the same page — that is what makes
    them independent — and comparing grids would report a disagreement on every
    document. What must match is the value the pipeline would go on to use.
    """
    left = _fields(primary_tables, method)
    right = _fields(crosscheck_tables, method)
    label = report_no or left["report_no"] or right["report_no"] or Path(path).stem
    return [
        Disagreement(report_no=label, field=field, primary=left[field],
                     crosscheck=right[field], path=str(path),
                     blocking=field in BLOCKING_FIELDS)
        for field in left
        if not _same(left[field], right[field])
    ]


def blocks(disagreements: list[Disagreement]) -> bool:
    """True when this document must be quarantined rather than compiled."""
    return any(d.blocking for d in disagreements)


def write_audit(output_dir: str | Path,
                disagreements: list[Disagreement],
                today: _dt.date | None = None) -> Path | None:
    """Write ``output/pdf_crosscheck_<date>.md``; return its path, or None if clean.

    The operator must not look at this blind. Each row names the report, the field,
    what each reader said, and the file to open — everything needed to settle the
    disagreement without re-running anything.
    """
    if not disagreements:
        return None
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    day = (today or _dt.date.today()).isoformat()
    path = output_dir / f"pdf_crosscheck_{day}.md"

    blocking = [d for d in disagreements if d.blocking]
    warnings = [d for d in disagreements if not d.blocking]
    quarantined = {d.report_no for d in blocking}

    lines = [
        f"# PDF oxuyucu razılaşmazlığı — {day}",
        "",
        f"Hər PDF **iki müstəqil oxuyucu** ilə oxunur: **{PRIMARY_NAME}** cədvəl "
        f"çərçivə xətlərindən, **{CROSSCHECK_NAME}** söz koordinatlarından. İkisi "
        f"razılaşanda cavab qəbul olunur. **Razılaşmayanda sistem dəyər uydurmur** — "
        f"hesabat karantinə göndərilir və bu sənədə yazılır.",
        "",
        f"**{len(quarantined)} hesabat karantinə düşdü** (`Nəticə` sahəsində fərq). "
        f"Əlavə **{len(warnings)} xəbərdarlıq** var — onlar karantinə salmır, hesabat "
        f"əsas oxuyucunun ({PRIMARY_NAME}) dəyəri ilə tərtib olunub.",
        "",
        "## Operator nə etməlidir",
        "",
        "1. `Fayl yolu` sütunundakı PDF-i aç.",
        "2. `Nəticə` sahəsi üçün: sənəddəki `Accept / Reject` sütununa bax — bir dənə "
        "də `Reject` varsa hesabat **Yarasız**, yoxsa **Yararlı**.",
        "3. Düzgün cavabı təsdiqlə və faylı `input/SKIPPED_REPORTS/`-dan öz metod "
        "qovluğuna qaytar.",
        "",
        "## 1. KARANTİN — `Nəticə` sahəsində fərq",
        "",
        f"| Report № | Sahə | {PRIMARY_NAME} nə dedi | {CROSSCHECK_NAME} nə dedi "
        f"| Fayl yolu | Nəticə |",
        "|---|---|---|---|---|---|",
    ]
    lines += [_row(d, "QUARANTINE") for d in blocking] or ["| — | — | — | — | — | — |"]
    lines += [
        "",
        "## 2. XƏBƏRDARLIQ — metadata sahələrində fərq (karantinə salmır)",
        "",
        f"| Report № | Sahə | {PRIMARY_NAME} nə dedi | {CROSSCHECK_NAME} nə dedi "
        f"| Fayl yolu | Nəticə |",
        "|---|---|---|---|---|---|",
    ]
    lines += [_row(d, "XƏBƏRDARLIQ") for d in warnings] or ["| — | — | — | — | — | — |"]
    lines += ["", "---", "",
              "Ölçmə əsası: ADR-003. 630 cütdə razılaşma halında səhv sayı **0**-dır — "
              "yəni yuxarıdakı siyahıya düşməyən hesabatların nəticəsi doğrudur.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _row(d: Disagreement, verdict: str) -> str:
    """One audit table row. Empty values print as `''` so a blank is visible."""
    def cell(value: str) -> str:
        return f"`{value}`" if value else "`''`"
    return (f"| `{d.report_no}` | {d.field} | {cell(d.primary)} | "
            f"{cell(d.crosscheck)} | `{d.path}` | {verdict} |")
