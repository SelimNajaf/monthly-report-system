"""Guard the İtem / Detal translations (R4-D).

The operator approved ``docs/translation_review_2026-10-05.md`` with a final scope:
only values that render in the İtem / Detal column are translated; Üsul tokens,
report numbers, standards, dates, the verdict and identifiers stay as they are;
"weld" is "qaynaq" (S2).

Two layers, by design:

* hard tests: the dictionary holds what was approved and nothing outside the
  scope, and no 2026+ sidecar İtem carries the ``[AZ?]`` marker or a term
  ``az.json`` already translates (that can only mean a stale or regressed render);
* an audit line, not a test, for an English İtem ``az.json`` does not know yet.
  New LAN reports bring new wording every month; a test that failed on them would
  fail on the operator's data, not on a code defect. The coverage report lists
  them and ``main.py`` prints ``  İtem English (2026+): …`` (``audit.coverage_report``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from monthly_report import coverage_audit as C
from monthly_report.gui.services import progress, quarantine_reasons_service
from monthly_report.gui.ui.widgets import console_view
from monthly_report.translator import Translator, load_dictionary

_ROOT = Path(__file__).resolve().parent.parent
_AZ = _ROOT / "translations" / "az.json"


@pytest.fixture(scope="module")
def az():
    return Translator(load_dictionary(_AZ))


@pytest.mark.parametrize("english, azerbaijani", [
    ("Structural weld", "Konstruktiv qaynaq"),
    ("Structural welds", "Konstruktiv qaynaqlar"),
    ("Weld", "Qaynaq"),
    ("Sructural weld", "Konstruktiv qaynaq"),
    ("Piping weld", "Boru kəməri qaynağı"),
    ("Spool-1; Weld-SW1", "Spul-1; Qaynaq-SW1"),
    ("Pipe to flange", "Boru-flans"),
    ("Reduction to Pipe", "Reduksiya-boru"),          # one row, case ignored
    ("MPD Riser Crossover\n(Lower adapter)", "MPD rayzer keçid hissəsi (aşağı adapter)"),
    ("SPOOL (5”)", "Spul (boru seksiyası) (5”)"),
    ("WQT", "Qaynaqçının ixtisas sınağı (WQT)"),
    ("Pins", "Pinlər (ştiftlər)"),
])
def test_approved_items_translate(az, english, azerbaijani):
    assert az.term(english) == azerbaijani


def test_weld_is_qaynaq_except_the_two_unrendered_labels():
    raw = json.loads(_AZ.read_text(encoding="utf-8"))
    tikis = sorted(k for k, v in raw.items() if k != "_meta" and "tikiş" in v.lower())
    # Weld ID / WDR ID are labels, not İtem values, with no render call in src/:
    # out of the R4-D scope, so they keep their value.
    assert tikis == ["WDR ID", "Weld ID"]
    assert raw["Weld ID"] == raw["WDR ID"] == "Qaynaqçı / Tikiş İD"


@pytest.mark.parametrize("key, value", [
    ("Row Number", "Sıra №"), ("Date", "Tarix"), ("Report No", "Report №"),
    ("Standard", "Standart"), ("Method", "Üsul"), ("Item / Detail", "İtem / Detal"),
    ("Result", "Nəticə"), ("Facility", "Obyekt"), ("Report Number Label", "Hesabat №"),
    ("Fit", "Yararlı"), ("Unfit", "Yarasız"), ("Info", "Məlumat üçün"),
])
def test_labels_and_verdicts_are_untouched(az, key, value):
    assert az.term(key) == value


@pytest.mark.parametrize("token", [
    # Üsul tokens, identifiers kept as is (review table 3) and the method acronym
    # that sat in one İtem cell: none may become a dictionary key.
    "MT", "UT", "RT", "DP", "PT", "HrT", "PMI", "MPI", "UTM", "FC",
    "DB-2", "M1-M1A", "M1", "DB1", "DB2", "M1-D", "10E-389-01-A", "FC-07D047-01",
    "ST-DTL-014832-D-002-001 C01",
    # Not İtem values (old review section 4).
    "S/N", "Qty", "DetailNo", "Number of holes", "N/A", "—",
])
def test_out_of_scope_values_are_not_keys(az, token):
    assert az.lookup(token) is None
    assert az.term(token) == token


def _sidecars_2026():
    out = _ROOT / "output"
    return sorted(p for p in out.glob("*/compiled_monthly_report_*.json")
                  if p.stem[-4:].isdigit() and int(p.stem[-4:]) >= 2026)


def test_no_2026_sidecar_item_is_marked_or_left_in_known_english(az):
    sidecars = _sidecars_2026()
    if not sidecars:
        pytest.skip("no 2026+ sidecar under output/ (fresh machine)")
    bad = []
    for path in sidecars:
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("items_table") or []:
            item = str(row.get("item_name") or "")
            hit = az.lookup(item)
            if "[AZ?]" in item or (hit is not None and hit != item.strip()):
                doc = "_".join(path.stem.split("_")[-3:])
                bad.append((doc, row.get("report_no"), item))
    assert bad == [], ("re-run `python main.py`: these sidecars predate az.json", bad)


# --------------------------------------------------------------------------- #
# The audit line


@pytest.mark.parametrize("text, english", [
    ("Gearbox housing", True), ("GOOSENECK, SWIVEL", True), ("Pipe 6”", True),
    ("Boru kəməri", False), ("Şimal kranı C100B80X939", False),
    ("DB-2", False), ("M1-M1A", False), ("10E-389-01-A", False), ("", False),
])
def test_looks_english(text, english):
    assert C.looks_english(text) is english


def _collector(tmp_path, dictionary):
    (tmp_path / "input").mkdir()
    az = tmp_path / "az.json"
    az.write_text(json.dumps(dictionary), encoding="utf-8")
    s = SimpleNamespace(input_dir=tmp_path / "input", project_root=tmp_path,
                        output_dir=tmp_path / "output", translations_path=az,
                        raw={"audit": {"coverage_report": True}, "clients": {},
                             "ndt_methods": {}})
    return C.Collector(s)


def test_the_audit_lists_only_2026_english_items_az_json_lacks(tmp_path):
    col = _collector(tmp_path, {"Pipe": "Boru"})
    row = lambda item: SimpleNamespace(source_path=None, item_detail=item)
    col.add_report("2026-05", "KHF", "KHF MAY 2026", SimpleNamespace(
        rows=[row("Pipe"), row("Gearbox housing"), row("Gearbox housing"),
              row("DB-2"), row("Boru kəməri"), row("[AZ?] x")], skipped=[]), None)
    col.add_report("2025-05", "KHF", "KHF MAY 2025", SimpleNamespace(
        rows=[row("Valve body")], skipped=[]), None)
    col.add_report("2026-06", "KHF", "KHF JUN 2026", SimpleNamespace(
        rows=[row("Valve body")], skipped=[]), "low volume")       # not rendered
    path, _totals = C.write(col, tmp_path / "output")
    assert col.english == [("Gearbox housing", 2, ["KHF MAY 2026"]),
                           ("[AZ?] x", 1, ["KHF MAY 2026"])]
    assert C.item_line(col.english) == \
        "  İtem English (2026+): 2 value(s), 3 row(s) not in az.json"
    text = path.read_text(encoding="utf-8")
    assert "### İtem / Detal not in az.json, 2026+ (2)" in text
    assert "| `Gearbox housing` | 2 | KHF MAY 2026 |" in text


def test_the_audit_is_empty_without_a_dictionary(tmp_path):
    col = _collector(tmp_path, {})
    col.settings.translations_path = tmp_path / "missing.json"
    assert C.english_items(col) == []
    assert C.item_line([]) == "  İtem English (2026+): 0 value(s), 0 row(s) not in az.json"


@pytest.mark.parametrize("english", [[], [("Gearbox housing", 2, ["KHF MAY 2026"])]])
def test_no_gui_regex_claims_the_audit_line(english):
    line = C.item_line(english)
    assert line.startswith("  ") and not line.lstrip().startswith("[")
    assert progress.PipelineProgressParser().feed(line) is None
    patterns = [v for v in vars(progress).values() if isinstance(v, re.Pattern)]
    assert not any(p.search(line) for p in patterns)
    assert quarantine_reasons_service.parse_line(line) is None
    for pattern, attribute, _bold in console_view._RULES:
        assert not pattern.search(line), attribute


def test_main_prints_the_audit_line_only_behind_the_coverage_switch():
    src = (_ROOT / "main.py").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert ("            safe_print(coverage_audit.coverage_line(*totals))\n"
            "            safe_print(coverage_audit.item_line(coverage.english))\n") in src
