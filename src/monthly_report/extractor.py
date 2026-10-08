"""Header-driven extraction of report metadata and weld rows.

The reports carry all data in tables, but the weld-table column layout **drifts
between reports** (some have ``DRW``, others ``Line No`` or ``Qty``; column order
varies). So we never read by fixed column index: we locate the weld header row,
map each header cell to a canonical field name, and read data rows against that
map. Missing fields yield ``""`` rather than crashing, keeping evolving layouts
robust (per the error-handling-recovery design).

I/O contract
------------
extract_meta(tables)  -> dict[str, str]        # report_no, date, client, drw, ...
extract_welds(tables) -> list[dict[str, str]]  # canonical keys per weld row
"""

from __future__ import annotations

import re

# --- label / header normalisation ------------------------------------------

# Metadata labels found in the header block -> canonical key.
_META_LABELS = {
    "report no": "report_no",
    "job no": "job_no",
    "project": "project",
    "date": "date",
    "client": "client",
    "location": "location",
    "acc standard": "acc_standard",
    "acceptance standard": "acc_standard",
    "acceptance criteria": "acc_standard",
    "normative document": "acc_standard",
    "code standard": "acc_standard",   # _norm("Code/Standard:") == "code standard"
    "specification": "specification",
    "drw": "drw",
    "item": "item",
    "item inspection": "item",   # RT template label ("Item Inspection: Pipe")
    "description": "description",
    "procedure": "procedure",
    "material": "material",
}

# Rows whose first non-empty cell starts like this end the weld-data block.
_TERMINATORS = ("evaluated", "ndt tech", "ndt technician", "mpi 100", "contractor", "name:")

# Normalized values that are header/placeholder tokens, never a real item name.
# Deny-list of results/service column headers that inspectors' templates sometimes
# leak into the document-level Item: field or a weld "item" cell (e.g. a report
# whose metadata literally reads `Item: Spool No.`). Matching is exact on the
# _norm form (lowercased, punctuation reduced to single spaces): "Spool No." ->
# "spool no", "Diam./Thick." -> "diam thick", "Weld length, mm" -> "weld length
# mm", "PN,and S/N numbers" -> "pn and s n numbers". When a leaked header is
# caught the caller falls back to Description, then to the weld item, then to ""
# (never renders the header as the item).
_ITEM_BADSET = {"", "item", "item insp", "item inspection", "weld no", "weld size",
                "drw", "drawing", "thk", "thk mm", "diam thick", "weld length",
                "weld length mm", "result", "wdr", "wdr id", "wdr no",
                "interpretation", "film section", "defects", "accept reject",
                "type", "no", "na", "size", "size mm", "spool no",
                "pn and s n numbers"}

# Results-table COLUMN headers that sit right of an "Item" column header. When a
# template's header row reads ``Item | Qty | ...``, the label scan in
# :func:`extract_item_global` takes "Item" for the Item: label and the next header
# for its value (measured R2/R3: "Qty", "S/N", "DetailNo", "Detail No", "Number
# of holes"). "N/A" is the not-applicable placeholder: never an item's name.
# Opt-in (``filtering.reject_item_header_labels``): rejecting them changes the
# Item of already compiled rows, so it is the operator's switch.
_ITEM_HEADER_LABELS = {"qty", "s n", "detailno", "detail no", "number of holes", "n a"}

# A real weld id looks like W12, SW1, 065, M1 — up to a few letters then a digit.
_WELD_ID = re.compile(r"^[A-Za-z]{0,4}\d")


def _norm(text: str) -> str:
    """Lowercase, strip punctuation to spaces, collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (text or "").lower())).strip()


def _canonical_header(cell: str) -> str | None:
    """Map a weld-table header cell to a canonical field name, or None to ignore."""
    n = _norm(cell)
    if not n:
        return None
    if "weld no" in n:
        return "weld_no"
    if "wdr" in n:
        return "wdr_id"
    if n.startswith("item"):
        return "item"
    if "drw" in n or "drawing" in n:
        return "drw"
    if "line no" in n:
        return "line_no"
    if "interpret" in n:
        return "interpretation"
    # Verdict column. Header wording drifts between templates: "Result",
    # "Accept/Reject", "Result Accept/Reject", "Acceptance", "Status",
    # "Disposition", "Remark(s)". Matching is on the already-lower-cased _norm,
    # so it is inherently case-insensitive.
    if any(tok in n for tok in ("result", "accept", "status", "disposition",
                                "remark", "conclusion")):
        return "result"
    return None


def _is_weld_header(row: list[str]) -> dict[str, int] | None:
    """If ``row`` is a weld-table header, return {canonical_field: column_index}."""
    mapping: dict[str, int] = {}
    for idx, cell in enumerate(row):
        key = _canonical_header(cell)
        if key and key not in mapping:
            mapping[key] = idx
    if "weld_no" in mapping and "result" in mapping:
        return mapping
    return None


# --- public API -------------------------------------------------------------

def _value_after(row: list[str], i: int) -> str:
    """Return the label value at ``row[i]``, scanning right past empty cells.

    A merged/blank cell (common on ACC-Standard rows) leaves ``row[i+1]`` empty
    while the real value sits one or more columns further right. We scan rightward
    for the first non-empty cell, but stop if it is itself a known label — that
    means this field's own value is genuinely absent and the next cell belongs to
    a different field.
    """
    for j in range(i + 1, len(row)):
        cand = (row[j] or "").strip()
        if not cand:
            continue
        if _norm(cand).rstrip() in _META_LABELS:   # reached the next label
            return ""
        return cand
    return ""


def extract_meta(tables: list[list[list[str]]]) -> dict[str, str]:
    """Scan label/value cells across all tables into a flat metadata dict."""
    meta: dict[str, str] = {}
    for table in tables:
        for row in table:
            for i, cell in enumerate(row):
                label = _norm(cell).rstrip()
                key = _META_LABELS.get(label)
                if key and key not in meta:
                    value = _value_after(row, i)
                    if value:
                        meta[key] = value
    return meta


# Standard/acceptance-criteria label triggers, in preference order (specific
# first, broad ``specification`` last). All are the _norm-ed form, so every
# punctuation/case variant collapses onto them: "ACC Standard:", "ACC. Standard",
# "Acc-Standard" -> "acc standard"; "Code/Standard:" -> "code standard".
_STANDARD_LABELS = (
    "acc standard",
    "acceptance standard",
    "acceptance criteria",
    "normative document",
    "code standard",
    "specification",
)


def extract_standard(tables: list[list[list[str]]]) -> str:
    """Return the ACC Standard / Specification from the metadata block, robustly.

    Handles two cell layouts, mirroring ``extract_item_global``: a **merged single
    cell** carrying label and value together (``"ACC Standard: EEMUA 158"`` — the
    common PDF-conversion artifact) via ``partition(":")``, and a **separate label
    cell** whose value sits one or more columns right (``_value_after`` skips the
    blank cells a merged layout leaves). Recognizes several label wordings
    (``_STANDARD_LABELS``), preferring ``ACC Standard`` and treating ``Specification``
    as the last resort. Returns ``""`` when nothing carries a usable (non ``N/A``)
    value.
    """
    for wanted in _STANDARD_LABELS:
        for table in tables:
            for row in table:
                for i, cell in enumerate(row):
                    text = (cell or "").strip()
                    if not text:
                        continue
                    # Merged "ACC Standard: EEMUA 158" style (label + value in one).
                    if ":" in text:
                        label, _, inline = text.partition(":")
                        if _norm(label).rstrip() == wanted:
                            value = inline.strip()
                            if value and value.upper() != "N/A":
                                return value
                    # Separate label cell; value in a cell to the right.
                    if _norm(text).rstrip() == wanted:
                        value = _value_after(row, i)
                        if value and value.strip().upper() != "N/A":
                            return value.strip()
    return ""


def item_is_bad(value: str, header_labels: bool = False) -> bool:
    """True if empty/whitespace, a trailing-colon caption, or a leaked header token.

    A value ending in ``:`` is never this item's name — it is the NEXT field's
    caption, picked up because the template put label and value in separate cells
    and the value cell was left blank ("Production stage:"). The test is on the RAW
    text: :func:`_norm` strips punctuation, so the colon is gone by the time the
    deny-list is consulted, and no entry in ``_ITEM_BADSET`` could catch it. Unlike
    the deny-list this rule is shape-based, so it also holds for the next template
    the corpus grows.

    ``header_labels=True`` also rejects the column headers and placeholder in
    :data:`_ITEM_HEADER_LABELS` (``filtering.reject_item_header_labels``).
    """
    if (value or "").rstrip().endswith(":"):
        return True
    if header_labels and _norm(value) in _ITEM_HEADER_LABELS:
        return True
    return _norm(value) in _ITEM_BADSET


def extract_item_global(tables: list[list[list[str]]],
                        header_labels: bool = False) -> str:
    """Return the document's global inspected-item name from the metadata block.

    The label differs by template: ``Item:`` (Platform U-UT / RT reports),
    ``Item Insp.:`` (KF-UT / KF-MT) or ``Item Inspection:`` (RT: KF/BS/AZF). It
    appears either as a ``label | value`` cell pair or as a single merged cell
    (``"Item Insp.: Structural Welds"``). Values that are header tokens (e.g. the
    results-table ``Item | Weld No`` header) are rejected. Returns ``""`` when no
    clean global item is present. ``header_labels`` is passed to
    :func:`item_is_bad`: a rejected header value lets the scan go on to the next
    ``Item`` label instead of returning it.
    """
    item_labels = ("item", "item insp", "item inspection")
    for table in tables:
        for row in table:
            for i, cell in enumerate(row):
                text = (cell or "").strip()
                if not text:
                    continue
                # Merged "Item Insp.: Structural Welds" style (label + value in one).
                if ":" in text:
                    label, _, inline = text.partition(":")
                    if (_norm(label) in item_labels
                            and not item_is_bad(inline, header_labels)):
                        return inline.strip()
                # Separate label cell; value in the next cell.
                if _norm(text) in item_labels:
                    value = row[i + 1].strip() if i + 1 < len(row) else ""
                    if not item_is_bad(value, header_labels):
                        return value
    return ""


# --- Equipment / instrument extraction --------------------------------------
#
# The instrument that performed the inspection, for the JSON sidecar's
# equipment_used key and the portal's "İstifadə olunmuş avadanlıqlar barədə
# qeyd:" field. It is NEVER rendered in the PDF (that table stays at its 6
# columns) — this is a digital-only payload.

# Equipment labels in _norm form, preference-ordered. One label per method and
# they never co-occur in a document, so this needs no method parameter:
#   equipment used   -> MT/MPI, PMI, FERRITE (FC), HT (HrT)
#   ut set type s n  -> UT and UTM. _norm reduces & / : № to spaces, so UT's
#                       "UT Set type & S/N" and UTM's "UT Set type/S/n:" — which
#                       are genuinely spelt differently — collapse onto this one
#                       key.
#   radiation source -> RT (the value is the isotope: "Ir 192", "Se 75")
# DP carries no equipment label at all (only Consumables / Lighting Equipment),
# and correctly yields "" — the field is optional by design.
_EQUIPMENT_LABELS = ("equipment used", "ut set type s n", "radiation source")

# Normalized PREFIXES of cells that sit beside an equipment value but are never
# one. Prefix, not exact match, because each carries its own trailing value:
# "Power: 110V 220V" -> "power 110v 220v", "Calibration Block (HV)" ->
# "calibration block hv". These matter because a blank value cell would
# otherwise hand back the neighbouring field's text — "X-ray" in particular is
# RT's checkbox alternative sitting one cell right of the isotope.
_EQUIP_BAD_PREFIXES = ("x ray", "power", "couplant", "calibration block",
                       "calibration date", "calibration standard", "film type",
                       "consumables", "reference block", "n a")


def _equipment_is_bad(value: str) -> bool:
    """True if ``value`` is empty, a neighbouring field's text, or a label."""
    n = _norm(value)
    if not n:
        return True
    if n in _EQUIPMENT_LABELS or n in _META_LABELS:
        return True
    return any(n.startswith(bad) for bad in _EQUIP_BAD_PREFIXES)


def extract_equipment(tables: list[list[list[str]]]) -> str:
    """Return the NDT instrument named in the document's Equipment block, or ``""``.

    Reads the value **strictly adjacent** to the label — never :func:`_value_after`.
    That helper scans rightward past empty cells and stops only at a
    ``_META_LABELS`` entry, so on a document whose value cell is blank it would
    return the next field along: ``Power: 110V 220V`` (MPI), ``X-ray`` (RT) or
    ``Calibration Block (HV)`` (HT). An absent instrument must read ``""``, not a
    plausible-looking wrong one.

    Both cell shapes are handled, as in :func:`extract_item_global`: the merged
    ``"Radiation source: Ir.192"`` single cell, and the ``label | value`` pair.
    The value is returned as written apart from whitespace squashing — the corpus
    contains an unbalanced paren (``"SIUI CTS-9006 (№540331110056"``) and we do
    not repair source data. A split serial (PMI's ``S/N: 56860`` in the *next*
    cell) is likewise not merged in.
    """
    for wanted in _EQUIPMENT_LABELS:
        for table in tables:
            for row in table:
                for i, cell in enumerate(row):
                    text = (cell or "").strip()
                    if not text:
                        continue
                    # Merged "Radiation source: Ir.192" style (label + value in one).
                    if ":" in text:
                        label, _, inline = text.partition(":")
                        if _norm(label) == wanted and not _equipment_is_bad(inline):
                            return _squash(inline)
                    # Separate label cell; value strictly in the next cell.
                    if _norm(text).rstrip() == wanted:
                        value = row[i + 1] if i + 1 < len(row) else ""
                        if not _equipment_is_bad(value):
                            return _squash(value)
    return ""


# Leading-cell prefixes that mark a sign-off strip header row (any of the three
# NDT sign-off templates). Kept in sync with _INSPECTOR_LABELS below.
_SIGN_HEADER_PREFIXES = ("evaluated", "ndt technician", "ndt tech", "technician",
                         "inspected by")

# Role/header words that must never be mistaken for a person's name (they are the
# adjacent COLUMN headers of the sign-off strip, not values).
_ROLE_WORDS = {"contractor", "client", "evaluated by", "evaluator", "name",
               "signature", "date"}


def extract_signatures(tables: list[list[list[str]]]) -> dict[str, str]:
    """Pull Evaluator / Contractor / Client signatory names from the sign-off block.

    The block is a 3-column strip: header row (``Evaluated by ...`` | ``Contractor``
    | ``Client``) followed by a ``Name:`` row whose value cells hold the names.
    Returns ``{"evaluator": .., "contractor": .., "client": ..}`` ("" when absent).
    """
    roles = ["evaluator", "contractor", "client"]
    for table in tables:
        for ri, row in enumerate(row_list := table):
            # The signer column header varies by template: "Evaluated by ..." on
            # MT/UT/RT, but "NDT Technician / ISO 9712 ..." on UTM/DP/PMI. Trigger
            # on any of these so the following "Name:" row is read either way.
            if any(any(_norm(c).startswith(h) for h in _SIGN_HEADER_PREFIXES)
                   for c in row):
                # find the following row that carries Name: labels
                for nrow in row_list[ri + 1: ri + 4]:
                    labels = [_norm(c) for c in nrow]
                    if any(l.startswith("name") for l in labels):
                        names = [nrow[i + 1].strip() if i + 1 < len(nrow) else ""
                                 for i, l in enumerate(labels) if l.startswith("name")]
                        return {roles[i]: (names[i] if i < len(names) else "")
                                for i in range(len(roles))}
    return {r: "" for r in roles}


_INSPECTOR_LABELS = ("ndt technician", "ndt tech", "technician", "inspector",
                     "inspected by", "operator")


def extract_inspector_name(tables: list[list[list[str]]]) -> str:
    """Return an explicitly labelled NDT Technician / Inspector name, or ``""``.

    Handles both the ``NDT Technician: <name>`` label/value form (value in the
    same row, possibly across merged cells) and a header cell followed by a
    ``Name:`` row. Used as a fallback for the sign-off block when the ``Evaluated
    by`` evaluator name is absent.
    """
    for table in tables:
        for ri, row in enumerate(table):
            for i, cell in enumerate(row):
                n = _norm(cell)
                if not any(n.startswith(lbl) for lbl in _INSPECTOR_LABELS):
                    continue
                # "NDT Technician: John Doe" merged into one cell.
                if ":" in (cell or ""):
                    _lbl, _, inline = cell.partition(":")
                    if inline.strip():
                        return _squash(inline)
                # Value to the right on the same row — but not when it is itself a
                # sign-off column header (e.g. the "Contractor"/"Client" cells that
                # sit beside an "NDT Technician" header); those live in a 3-column
                # strip whose real names are in the following "Name:" row.
                value = _value_after(row, i)
                if value and _norm(value) not in _ROLE_WORDS:
                    return _squash(value)
                # Value in a following "Name:" row (sign-off strip layout).
                for nrow in table[ri + 1: ri + 4]:
                    for j, c in enumerate(nrow):
                        if _norm(c).startswith("name"):
                            v = _value_after(nrow, j)
                            if v:
                                return _squash(v)
    return ""


def _squash(text: str) -> str:
    """Collapse internal whitespace/newlines to single spaces."""
    return re.sub(r"\s+", " ", (text or "").strip())


def extract_welds(tables: list[list[list[str]]]) -> list[dict[str, str]]:
    """Return one canonical dict per weld data row, across all weld tables."""
    welds: list[dict[str, str]] = []
    for table in tables:
        header: dict[str, int] | None = None
        for row in table:
            if header is None:
                header = _is_weld_header(row)
                continue
            # inside a weld block
            nonempty = [c for c in row if c and c.strip()]
            if not nonempty:
                continue  # blank spacer row
            first = _norm(nonempty[0])
            if any(first.startswith(t.rstrip(":")) for t in _TERMINATORS):
                header = None  # block ended; keep scanning for another header
                continue
            rec = {field: (row[idx].strip() if idx < len(row) else "")
                   for field, idx in header.items()}
            # Guard: a data row must carry a real weld id. This rejects header /
            # sub-header rows (e.g. 'Weld No', 'Type') that share the block.
            if not _WELD_ID.match(rec.get("weld_no", "")):
                continue
            # Result is always the rightmost meaningful cell. Reading it by header
            # index breaks when a merged sub-header (UT 'DEFECTS DETAILS') expands
            # the data row's column count; the rightmost non-empty cell is robust.
            rightmost = next((c.strip() for c in reversed(row) if c and c.strip()), "")
            if rightmost:
                rec["result"] = rightmost
            welds.append(rec)
    return welds


# --- Radiographic (RT) extraction ------------------------------------------
#
# RT reports use a distinct layout that the generic ``extract_welds`` above
# mis-reads: the weld ids carry a separator before the digit ("CO - 1",
# "FW 2RW3", "QB-1") which the strict ``_WELD_ID`` guard rejects, and each weld
# spans several *film-section* rows. So RT gets its own reader. Touching the
# shared guard is deliberately avoided to keep MT/UT extraction stable.

# A row that starts the "INSPECTION RESULT" data block.
_RT_RESULT_HEADER = "inspection result"
# First-cell tokens that mark the end of the RT data block.
_RT_BLOCK_END = ("interpretation", "technique", "evaluated")
# Normalized first-cell values of the two RT result header rows (label varies:
# "Weld No" or just "Weld").
_RT_HEADER_FIRST = {"weld", "weld no"}


def extract_rt_welds(tables: list[list[list[str]]]) -> list[dict[str, str]]:
    """Return one canonical dict per **film section** from a Radiographic report.

    Each RT weld is radiographed in several *film sections* (``A``/``B``/``C`` or
    exposure ranges ``0 - 17``/``17 - 35``), and each section carries its own
    Accept/Reject verdict. This reader locates the ``INSPECTION RESULT`` block and
    emits **one record per section row** (not one aggregated weld), so the monthly
    table can show every section on its own line.

    Layout handling:
      * The block has two header rows; on either we locate the ``Film Section``
        column by header text (its position is otherwise template-dependent).
      * The ``Weld No`` / ``WDR ID`` cells are vertically merged (``python-docx``
        repeats them down the spanned rows, or they read ``N/A`` / ``Təkrar``); we
        carry the last non-empty value down so every section keeps its weld id.
      * The verdict is the **last column** (``Result / Accept / Reject``).
      * Trailing **pad rows** (empty result) are skipped; non-sectioned variants
        (e.g. KF ``SW7``) simply yield a single record with ``film_section=""``.

    Yields ``[{"weld_no", "wdr_id", "film_section", "result"}]``.
    """
    welds: list[dict[str, str]] = []
    for table in tables:
        in_block = False
        fs_idx: int | None = None          # Film Section column index (from header)
        last_weld = ""
        last_wdr = ""
        for row in table:
            cells = [(c or "").strip() for c in row]
            if not in_block:
                if _RT_RESULT_HEADER in _norm(" ".join(cells)):
                    in_block = True
                continue
            first = cells[0] if cells else ""
            nfirst = _norm(first)
            if any(nfirst.startswith(t) for t in _RT_BLOCK_END):
                break  # block ended (Interpretation / Technique / Evaluated)
            last = cells[-1] if cells else ""
            if nfirst in _RT_HEADER_FIRST or _norm(last) == "result accept reject":
                # One of the two result header rows: learn the Film Section column.
                for idx, cell in enumerate(cells):
                    if "film section" in _norm(cell):
                        fs_idx = idx
                        break
                continue
            # Data row. Carry down merged weld id / WDR id (update only when set).
            if first:
                last_weld = first
            if len(cells) > 1 and cells[1]:
                last_wdr = cells[1]
            if not last:
                continue  # pad row (no verdict) -> skip
            film = cells[fs_idx] if (fs_idx is not None and fs_idx < len(cells)) else ""
            welds.append({"weld_no": last_weld, "wdr_id": last_wdr,
                          "film_section": film, "result": last})
    return welds
