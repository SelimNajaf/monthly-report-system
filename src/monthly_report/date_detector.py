"""Detect the primary inspection date and filter reports by month.

Inspection dates in the real reports are entered by humans and are frequently
*ranges* or *multi-day* strings, e.g. ``14.01.2026``, ``18,26.01.2026`` (welded
on the 18th and 26th), ``21-26.05.2026``. We take the **first** day of such a
string paired with its trailing ``MM.YYYY`` as the primary inspection date, which
is what determines the report's month.

Truncated years (KB-1)
----------------------
A recurring typing accident in the corpus is a year cut short — ``17.03.202``,
``02.04.2``, ``29.03.20``, and the flat ``25.06`` where the year was never typed
at all. dateutil parses those happily and invents a century with no plausibility
check, so ``'202'`` became the year 202 and ``'2'`` became 2002; the document
serial then collapsed both through ``year % 100`` and named phantom months.
Day and month are intact in these cells, and the report number carries the year
(``MT-U-25-028`` -> 2025), so the year is REPAIRED from the report number.

KB-1 fires only when the cell carries no 4-digit year at all AND still yields a
day and a month — i.e. the year is demonstrably missing rather than guessed at.

Truncated cells (KB-1b)
-----------------------
The larger accident is a *cut cell*: the inspector's ``Date:`` field holds only
``'11'``, ``'17.'``, ``'11.0'`` or ``'11        /'``. KB-1 cannot help — the month
is gone too — but the signed PDF original archived in ``input/PDF_ARCHIVE/`` is
named with the full date (``UT-SDLN-25-009(F1815)24"x 15.9_W-1_11.09.2025.pdf``).
KB-1b takes the MONTH and YEAR from that filename and, when the cell still shows a
readable day, keeps the CELL's day.

Why the day is treated differently from the month: the cell was cut from the right,
so whatever survives on its left — the day — is what the inspector actually typed
for *this* report. The filename's day belongs to the export/job it names, which for
a batch of welds filed together is frequently a day or two off (21 files in this
corpus disagree that way). The month, in every one of those, is the same. So the
month is safe to import and the day is not.

The one exception is a day the cut went *into*: a ONE-digit cell day against a
TWO-digit twin day starting with that same digit (``'1'`` against a twin dated the
10th). Every day in this corpus is typed two digits, so a lone digit is not a value
but the left half of one, and the twin holds the digit that was lost. Both digits
have to line up — ``'20'`` against a twin dated the 22nd keeps the cell's 20, because
two digits are a whole day. See :func:`_day_was_cut`.

KB-1b refuses to guess. It repairs only when:

  * the twin filename holds exactly ONE distinct full ``DD.MM.YYYY`` — two different
    dates in the name (or across two twins of the same report) is ambiguity, not
    evidence;
  * that filename year equals the report number's ``-<YY>-`` year — a filename that
    disagrees with the serial is describing something else;
  * the assembled date is a real calendar date — cell day 31 onto a February
    filename is refused, not rolled over;
  * and, when the cell does name a month of its own, that month agrees with the
    filename's.

Everything else — no twin, no full date in the name, a cell whose day is not a day
(``'WPS-002'``) and no filename day either — stays undatable and takes the existing
"no detectable inspection date" quarantine path, where a human can read the date off
the source document.

Order of attack, highest confidence first::

    4-digit year in the cell   -> parse the cell, untouched
    day + month in the cell    -> KB-1  (year from the report number)
    twin filename with a date  -> KB-1b (month/year from the name, day from the cell)
    otherwise                  -> None  (quarantine)

For the same reason the dateutil fallback — kept, not removed — is reached only when
the cell holds a 4-digit year: without one its century came from the system clock,
not the document, and the pipeline's output would depend on the calendar date of the
run. NOTE this also rejects a spelled-out short year (``'15 March 25'``); no cell in
this corpus is written that way (0 of 193 malformed cells contain a letter), and
inventing a year for one would be the very guess this module refuses to make.

I/O contract
------------
parse_inspection_date(raw, dayfirst=True, report_no="", twin_names=()) -> date | None
parse_inspection_date_ex(...) -> (date | None, DateRepair | None)
filename_dates(names) -> list[datetime.date]     # distinct full dates in filenames
cell_day(raw) -> int | None                      # the day still readable in a cell
is_in_month(date, target_month) -> bool          # target_month = "YYYY-MM"
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import NamedTuple

from dateutil import parser as _dateparser

from .report_identity import serial_year

_NUM = re.compile(r"\d+")

#: A standalone 4-digit run — the mark of a year the inspector actually typed in
#: full. Its ABSENCE is what licenses the repairs below and what disqualifies
#: dateutil's answer.
_YEAR4 = re.compile(r"(?<!\d)\d{4}(?!\d)")

#: A whole ``DD.MM.YYYY`` inside a filename. The 4-digit year is what makes it
#: unambiguous: the pipe sizes these names are full of (``6"x 18.26``, ``30"x
#: 38.0``, ``15.9``) never carry one, so they cannot be mistaken for a date.
_FULL_DATE = re.compile(r"(?<!\d)(\d{1,2})[.\-_](\d{1,2})[.\-_](\d{4})(?!\d)")

#: Any alphabetic character. A ``Date:`` cell holding letters (``'WPS-002'``) is not
#: a cut date, it is a different field entirely, so no day is read out of it.
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)

#: Repaired years must land in this window. The floor rules out a report number
#: whose ``-<YY>-`` never was a year; the ceiling rules out a future-dated one. Both
#: ends are facts about the corpus, not a guess: inspection reports are filed after
#: the inspection, and this project's oldest is 2024.
_MIN_YEAR = 2000


class DateRepair(NamedTuple):
    """What a repair did — carried back so the caller can print and audit it.

    ``source`` is ``"serial"`` (KB-1, year off the report number) or ``"filename"``
    (KB-1b, month+year off the PDF twin). ``day_source`` says where the day came
    from — ``"cell"``, ``"filename"`` (the cell showed no usable day), or
    ``"twin-truncated"`` (the cell showed the day's first digit only, see
    :func:`_day_was_cut`). ``day_delta`` is the day finally used minus the twin's,
    i.e. the disagreement an operator may want to check; it is 0 for a
    ``twin-truncated`` day because that day IS the twin's, and ``None`` when there is
    nothing to compare.
    """

    source: str
    day_source: str
    filename_date: _dt.date | None = None
    day_delta: int | None = None


def _repair_ceiling() -> int:
    """Latest acceptable repaired year: next year, so a January run of a report
    numbered for the year ahead is not rejected on an off-by-one."""
    return _dt.date.today().year + 1


def cell_day(raw: str) -> int | None:
    """The day still readable in a (possibly cut) ``Date:`` cell, or ``None``.

    The first integer run, and only when it can be a day: at most two digits and
    1..31. A cell carrying letters is rejected outright — ``'WPS-002'`` would
    otherwise donate the day 2.
    """
    text = (raw or "").strip()
    if not text or _LETTER.search(text):
        return None
    nums = _NUM.findall(text)
    if not nums or len(nums[0]) > 2:
        return None
    day = int(nums[0])
    return day if 1 <= day <= 31 else None


def filename_dates(names) -> list[_dt.date]:
    """Every distinct, real ``DD.MM.YYYY`` found across ``names``, in order.

    More than one means the caller must NOT repair: the name is describing two
    events and nothing in it says which one the report is.
    """
    out: list[_dt.date] = []
    for name in names:
        for day_s, month_s, year_s in _FULL_DATE.findall(name or ""):
            try:
                found = _dt.date(int(year_s), int(month_s), int(day_s))
            except ValueError:
                continue    # 31.02.2025 in a filename is not a date
            if found not in out:
                out.append(found)
    return out


def _cell_day_month(nums: list[str]) -> tuple[int, int] | None:
    """``(day, month)`` from a yearless cell's integer runs, or ``None``.

    Two shapes, both of them the same date with the year cut to different lengths:
    ``17.03.202`` (day, month, year remnant) and ``25.06`` (day, month — the year
    was never typed). The month is the run before the remnant in the first shape
    and the last run in the second.
    """
    if len(nums) >= 3:
        month_s = nums[-2]
    elif len(nums) == 2:
        month_s = nums[-1]
    else:
        return None
    try:
        month, day = int(month_s), int(nums[0])
    except ValueError:
        return None
    if 1 <= month <= 12 and 1 <= day <= 31:
        return day, month
    return None


def _day_was_cut(raw: str, day: int, twin_day: int) -> bool:
    """True when the cell's day looks like the twin's day with its last digit cut off.

    Three conditions, and all three are needed. The cell's day must be written as ONE
    digit; the twin's must be TWO; and the twin's first digit must be that single
    digit. ``'1'`` against a twin dated the 10th is then not the 1st of the month —
    it is ``'10'`` with the cut that emptied the rest of the cell taking the 0 as
    well. Every day in this corpus is typed two digits (``'01'``, ``'25'``), so a
    lone digit is itself the mark of the cut rather than a value.

    Deliberately narrow. ``'20'`` against a twin dated the 22nd keeps the cell's 20:
    two digits are a whole day, and a whole day is the inspector's answer for this
    report even when the export was filed two days later.
    """
    nums = _NUM.findall((raw or "").strip())
    return bool(nums) and len(nums[0]) == 1 and twin_day >= 10 and twin_day // 10 == day


def _repair_from_twin(nums, raw: str, report_no: str, twin_names):
    """KB-1b — month and year off the PDF twin's filename. See the module docstring."""
    found = filename_dates(twin_names)
    if len(found) != 1:
        return None, None           # no date, or an ambiguous pair of them
    twin = found[0]
    year = serial_year(report_no)
    if year is None or year != twin.year:
        return None, None           # unverifiable, or the name is about another year
    day = cell_day(raw)
    day_source = "cell"
    if day is None:
        day, day_source = twin.day, "filename"
    elif _day_was_cut(raw, day, twin.day):
        # The cut reached into the day itself; the twin holds the digit it took.
        day, day_source = twin.day, "twin-truncated"
    # A cell that named a month of its own must agree with the name; disagreement is
    # a contradiction between two sources, and this module does not pick a winner.
    both = _cell_day_month(nums)
    if both is not None and both[1] != twin.month:
        return None, None
    try:
        repaired_date = _dt.date(twin.year, twin.month, day)
    except ValueError:
        return None, None           # cell day 31 onto a 30-day filename month
    return repaired_date, DateRepair("filename", day_source, twin, day - twin.day)


def parse_inspection_date_ex(
    raw: str,
    dayfirst: bool = True,
    report_no: str = "",
    twin_names=(),
) -> tuple[_dt.date | None, DateRepair | None]:
    """``(date, repair)`` — the primary date, and how it was repaired (or ``None``).

    ``repair`` is a :class:`DateRepair` only when the date was NOT read whole out of
    the cell. Callers that can report it (the pre-processor) print and audit a line;
    the rest ignore it. See the module docstring for the rules.
    """
    if not raw and not twin_names:
        return None, None
    text = (raw or "").strip()
    nums = _NUM.findall(text)

    # Primary strategy: pull all integer runs. A well-formed inspection date ends
    # with month + 4-digit year; the first run is the (first) day. UNCHANGED — a
    # cell that satisfies this never reaches a repair, so every well-formed date
    # in the corpus behaves exactly as it did before KB-1, including a plausible
    # but old year like 2019.
    if len(nums) >= 3 and len(nums[-1]) == 4:
        try:
            year = int(nums[-1])
            month = int(nums[-2])
            day = int(nums[0])
            if 1 <= month <= 12 and 1 <= day <= 31:
                return _dt.date(year, month, day), None
        except ValueError:
            pass

    if not _YEAR4.search(text):
        # KB-1 — the cell still names a day and a month; only the year is missing.
        # Highest-confidence repair, and it stays ahead of KB-1b: the report number
        # is on the document itself, while a filename is an export artefact.
        both = _cell_day_month(nums)
        if both is not None:
            year = serial_year(report_no)
            if year is not None and _MIN_YEAR <= year <= _repair_ceiling():
                day, month = both
                try:
                    return _dt.date(year, month, day), DateRepair("serial", "cell")
                except ValueError:
                    pass            # 31.04 in the cell is not a date
        # KB-1b — the cell is cut past its month; the twin filename supplies it.
        repaired_date, how = _repair_from_twin(nums, text, report_no, twin_names)
        if repaired_date is not None:
            return repaired_date, how
        # Undatable. dateutil's answer is not consulted: without a 4-digit year it
        # substitutes today's month and year and the "date" would drift every
        # calendar month.
        return None, None

    # Fallback: let dateutil parse the first whitespace/comma-separated token. Only
    # reachable with a 4-digit year in the cell, so the century is the document's.
    token = re.split(r"[,\s]+", text)[0]
    for candidate in (token, text):
        try:
            return _dateparser.parse(candidate, dayfirst=dayfirst, fuzzy=True).date(), None
        except (ValueError, OverflowError):
            continue
    return None, None


def parse_inspection_date(
    raw: str,
    dayfirst: bool = True,
    report_no: str = "",
    twin_names=(),
) -> _dt.date | None:
    """Return the primary date from a possibly-messy date string, or None."""
    return parse_inspection_date_ex(raw, dayfirst, report_no, twin_names)[0]


def is_in_month(date: _dt.date | None, target_month: str) -> bool:
    """True when ``date`` falls inside the ``YYYY-MM`` calendar month."""
    if date is None:
        return False
    try:
        year_s, month_s = target_month.split("-")
        return date.year == int(year_s) and date.month == int(month_s)
    except (ValueError, AttributeError):
        return False
