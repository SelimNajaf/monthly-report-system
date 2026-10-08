"""Read PDF reports directly into the same table model ``docx_reader`` produces.

Why this module exists
----------------------
Until ADR-003 the pipeline converted every incoming PDF to ``.docx`` with
``pdf2docx`` and then parsed the conversion. The conversion shatters text: a
``Result`` header arrives as ``esult``, a ``Report No:`` label splits across two
cells, and the stacked ``Accept / Reject`` column header breaks into a lone
``Reject`` cell that ``document_aggregator._aggregate_result`` then reads as the
document verdict. Measured on 630 PDF/docx pairs, that path writes the wrong
verdict for 96 reports (15.2%). Reading the original PDF removes the whole class
of damage — every PDF in the corpus is Word/Excel output with a perfect text
layer, so there is nothing to recover by rasterising.

Two readers, one contract
-------------------------
No single geometry reconstruction is safe on its own:

* ``_tables_primary`` (B1, ``page.find_tables()``) is wrong on 9/630 — always on
  the RT film-section grid, where the ruling collapses a multi-row grid into one
  sparse table and ``Accept\\n…\\nReject`` lands in a single cell.
* ``_tables_crosscheck`` (B3-C, word-coordinate grid + header-band merge) is
  wrong on 10/630 — a disjoint set (FCM and MT templates).

The two failure sets do not intersect, which is the whole point: run both, and
when they agree the answer was correct in **all** 611 agreeing cases (zero silent
errors). Disagreement is never resolved by guessing — ``pdf_crosscheck`` sends
the report to quarantine. See ADR-003 for the full measurement.

I/O contract — identical to ``docx_reader`` so ``_read_one`` can dispatch on the
file suffix and every caller downstream stays untouched:

read_tables(path)   -> list[list[list[str]]]
read_document(path) -> (tables, has_text)
"""

from __future__ import annotations

import collections
import re
from pathlib import Path

import fitz  # PyMuPDF

from .extractor import _META_LABELS, _norm

#: Two words whose vertical centres differ by less than this belong to the same
#: text line. 3 pt is under half a line of 9-11 pt body text and above the
#: sub-pixel jitter Word leaves on a justified row.
_Y_TOL = 3.0

#: Horizontal gap that separates two cells on the same line. 6 pt is wider than
#: an inter-word space at report font sizes and narrower than the padding of the
#: narrowest column in the corpus.
_X_GAP = 6.0

#: Tuned? No. Nine (_Y_TOL, _X_GAP) combinations over ytol 2-5 / xgap 2-12 were
#: measured against the full corpus and changed the outcome for 0 reports — the
#: template failures are structural, not tolerance-sensitive. The constants stay
#: module-level named values rather than settings keys precisely because there is
#: nothing for an operator to tune.

#: A row carrying no digit anywhere is a header row. Data rows in these reports
#: always carry a digit (weld id, diameter, thickness, length, film number), so
#: this test never merges real data. Used by the header-band merge below.
_DATAISH = re.compile(r"\d")

#: Labels that may appear glued to their value inside one PDF table cell
#: ("Report No: RT-U-25-176"). ``_META_LABELS`` covers the header block the
#: extractor already knows; the rest are labels that occur in the corpus but
#: carry no meaning for extraction — they still have to be split, or the value
#: stays welded to its label and no lookup matches it.
_SPLIT_LABELS = set(_META_LABELS) | {
    "acc standard", "specification", "subject", "production stage", "line",
    "line no", "procedure", "drw", "diam thick", "weld no", "radiation source",
    "film type", "item insp", "equipment used", "ut set type s n", "location",
    "material", "job no", "report no", "date", "client",
}


def _split_label_cell(text: str) -> list[str]:
    """Split ``"Report No: RT-U-25-176"`` into ``["Report No:", "RT-U-25-176"]``.

    Word draws a header-block label and its value in one table cell far more
    often in PDF than in .docx, where they are usually separate ``<w:tc>``. The
    extractor looks the label up as a cell of its own and takes the *next* cell
    as the value, so an unsplit cell is invisible to it. Only splits on a label
    the corpus actually uses — an arbitrary colon inside a value ("Ratio: 1:2")
    is left alone.
    """
    text = (text or "").strip()
    if ":" in text:
        head, _, value = text.partition(":")
        if _norm(head) in _SPLIT_LABELS:
            return [head + ":", value.strip()]
    return [text]


def _tables_primary(doc) -> list[list[list[str]]]:
    """B1 — PyMuPDF's own table finder, with glued label cells split.

    Primary reader: 9 wrong out of 630 measured pairs. It reads ruling lines, so
    it reproduces the intended cell structure wherever the template actually
    draws its borders — which is every template except the RT film-section grid.
    """
    out: list[list[list[str]]] = []
    for page in doc:
        for table in page.find_tables().tables:
            out.append([
                [part for cell in row for part in _split_label_cell(cell)]
                for row in table.extract()
            ])
    return out


def _tables_crosscheck(doc, y_tol: float = _Y_TOL,
                       x_gap: float = _X_GAP) -> list[list[list[str]]]:
    """B3-C — word coordinates reassembled into a grid, ignoring ruling entirely.

    Cross-check reader: 10 wrong out of 630, on a set disjoint from B1's. Because
    it never looks at borders it survives the RT film-section grid that defeats
    B1, and because it never merges rows carrying digits it cannot invent a weld
    row.

    The **header-band merge** is what makes it usable at all. UT templates stack
    a column header vertically — ``Accept/`` on one text line, ``Reject`` on the
    next — and a plain word-row grid leaves that as a lone ``Reject`` cell, the
    exact shape ``_aggregate_result`` reads as a rejection. Gluing consecutive
    digit-free rows column-wise (by overlapping x-interval) rebuilds the one cell
    Word intended. Before the merge this reader was wrong on 62/630; after, 10.
    """
    out: list[list[list[str]]] = []
    for page in doc:
        out.append(_page_grid(page, y_tol, x_gap))
    return out


def _page_grid(page, y_tol: float, x_gap: float) -> list[list[str]]:
    """One page of words -> rows of cell strings (see ``_tables_crosscheck``)."""
    by_centre: dict[float, list[tuple[float, float, str]]] = collections.defaultdict(list)
    for x0, y0, x1, y1, word, *_ in page.get_text("words"):
        by_centre[round((y0 + y1) / 2, 1)].append((x0, x1, word))

    centres = sorted(by_centre)
    if not centres:
        return []

    # Group vertical centres into text lines. Chaining (comparing against the
    # previous centre, not the first of the group) is deliberate: a superscript
    # or a slightly raised glyph should extend its line, not start a new one.
    lines: list[list[float]] = []
    current = [centres[0]]
    for centre in centres[1:]:
        if centre - current[-1] <= y_tol:
            current.append(centre)
        else:
            lines.append(current)
            current = [centre]
    lines.append(current)

    def cells_of(line: list[float]) -> list[list]:
        words = sorted(w for centre in line for w in by_centre[centre])
        cells: list[list] = []
        buffer = [words[0][2]]
        left = words[0][0]
        right = words[0][1]
        for x0, x1, word in words[1:]:
            if x0 - right > x_gap:
                cells.append([left, right, " ".join(buffer)])
                buffer = [word]
                left = x0
            else:
                buffer.append(word)
            right = x1
        cells.append([left, right, " ".join(buffer)])
        return cells

    rows = [cells_of(line) for line in lines]

    def is_header(cells: list[list]) -> bool:
        return not any(_DATAISH.search(cell[2]) for cell in cells)

    merged: list[list[list]] = []
    for cells in rows:
        if merged and is_header(cells) and is_header(merged[-1]):
            previous = merged[-1]
            for x0, x1, text in cells:
                hit = next((c for c in previous if x0 < c[1] and c[0] < x1), None)
                if hit is None:
                    previous.append([x0, x1, text])
                    continue
                hit[0] = min(hit[0], x0)
                hit[1] = max(hit[1], x1)
                hit[2] = (hit[2] + " " + text).strip()
            previous.sort(key=lambda c: c[0])
            continue
        merged.append(cells)

    return [[cell[2] for cell in row] for row in merged]


def has_page_text(doc) -> bool:
    """True when any page carries a text layer.

    False means a scanned image: the file then travels the existing textless
    quarantine path in ``main.py``, exactly as a pasted-scan .docx does. Costs
    ~11 ms per PDF, so it is taken on the same open as the tables.
    """
    return any((page.get_text() or "").strip() for page in doc)


def read_document(path: str | Path) -> tuple[list[list[list[str]]], bool]:
    """Parse once; return ``(tables, has_text)`` — ``docx_reader``'s signature.

    Returns the **primary** reader's tables. The cross-check pass is a separate
    call (``read_both``) because only the PDF dispatch path needs it, while the
    cache and every extractor downstream want one grid.
    """
    doc = fitz.open(str(path))
    try:
        return _tables_primary(doc), has_page_text(doc)
    finally:
        doc.close()


def read_tables(path: str | Path) -> list[list[list[str]]]:
    """Return every table in the PDF as a 2D grid of cell text."""
    return read_document(path)[0]


def read_both(path: str | Path) -> tuple[list[list[list[str]]], list[list[list[str]]], bool]:
    """Parse once, return ``(primary_tables, crosscheck_tables, has_text)``.

    One ``fitz.open`` for both readers: the second pass costs a word list, not a
    second file open, and running them apart would double the I/O for no gain.
    """
    doc = fitz.open(str(path))
    try:
        return _tables_primary(doc), _tables_crosscheck(doc), has_page_text(doc)
    finally:
        doc.close()
