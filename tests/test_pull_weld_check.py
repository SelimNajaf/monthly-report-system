"""Pin ``retest.pull_weld_check`` — a cross-month parent must be the retest's own.

``retest_tracker.pull_cross_month_parents`` pulls the LATEST earlier original of a
retest's series. A report number can be reused for two jobs, and a file can carry
another report's content (``U-RT-26-005 (Zığ).docx`` holds U-RT-26-004, weld QB-4,
while its retests inspected QB-5), so on ``strict`` the parent has to prove it:

* welds readable on both sides — every retest weld (repair tail removed) must be
  a parent weld;
* welds unreadable on either side — filename job group, standard and item must
  all match;
* a parent that fails is not pulled, no older candidate is tried, and the reason
  lands in ``report.skipped``.

``off`` — the default — must be exactly the behaviour that predates the key.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report import retest_tracker as rt                      # noqa: E402
from monthly_report.config import load_settings                       # noqa: E402
from monthly_report.document_aggregator import (_row_from_doc,        # noqa: E402
                                                build_monthly_report)
from monthly_report.extractor import extract_meta                     # noqa: E402
from monthly_report.report_identity import resolve_report_no          # noqa: E402


class _Translator:
    untranslated: set = set()

    def term(self, text):
        return text


def _tables(report_no, date_str, standard="ISO 11666", item="Pipe"):
    return [[
        ["Report No:", report_no],
        ["Date:", date_str],
        ["Client:", "UBOC"],
        ["ACC Standard:", standard],
        ["Item:", item],
    ]]


@pytest.fixture
def settings():
    cfg = load_settings(str(_ROOT / "config" / "settings.yaml"))
    cfg.target_month = "2026-05"
    return cfg


def _mode(cfg, value):
    cfg.raw = {**cfg.raw, "retest": {"pull_weld_check": value}}
    return cfg


@pytest.fixture
def welds(monkeypatch):
    """Weld ids per table object — the weld-table layout has its own tests."""
    table_welds: dict[int, set] = {}

    def fake(tables, method):
        return set(table_welds.get(id(tables), set()))

    monkeypatch.setattr(rt, "weld_bases", fake)
    return table_welds


def _add(tmp_path, cache, name, report_no, date_str, **kw):
    p = tmp_path / name
    p.write_bytes(b"")
    cache[p] = _tables(report_no, date_str, **kw)
    return p


def _records(cache, paths, cfg):
    out = []
    for p in paths:
        meta = extract_meta(cache[p])
        rno, _ = resolve_report_no(meta, p)
        d = dt.datetime.strptime(meta["date"], "%d.%m.%Y").date()
        out.append(_row_from_doc(p, cache[p], meta, rno, d, cfg, "UT"))
    return out


def _pull(cfg, cache, records):
    refused: list = []
    rows = rt.pull_cross_month_parents(records, cache, cfg, "UT", "UBOC",
                                       row_builder=_row_from_doc, refused=refused)
    return [r.report_no for r in rows], refused


def _one_retest(tmp_path, parent_kw=None, retest_kw=None,
                parent_name="U-UT-26-010 (Platform).docx",
                retest_name="U-UT-26-010R1 (Platform).docx"):
    cache: dict = {}
    parent = _add(tmp_path, cache, parent_name, "U-UT-26-010", "20.02.2026",
                  **(parent_kw or {}))
    retest = _add(tmp_path, cache, retest_name, "U-UT-26-010R1", "18.05.2026",
                  **(retest_kw or {}))
    return cache, parent, retest


def test_mode_is_off_when_the_block_the_key_or_the_value_is_unknown(settings):
    class _Bare:
        raw = {}

    assert rt.pull_weld_check(_Bare()) == "off"
    assert rt.pull_weld_check(_mode(settings, "loose")) == "off"
    assert rt.pull_weld_check(_mode(settings, " Strict ")) == "strict"


def test_weld_bases_strip_repair_tails_slashes_and_header_text(monkeypatch):
    monkeypatch.setattr(rt.extractor, "extract_welds", lambda t: [
        {"weld_no": w} for w in
        ["QB-1/RW-1", "QB-5RW", "QB-5RW1", "W40R1", "W6/1", "Date:", "", " qb 4 "]])
    assert rt.weld_bases([[]], "UT") == {"QB-1", "QB-5", "W40", "W6", "QB4"}
    assert rt.weld_bases(None, "UT") == set()


def test_strict_refuses_a_parent_whose_welds_are_not_the_retests(
        tmp_path, settings, welds):
    cache, parent, retest = _one_retest(tmp_path)
    welds[id(cache[parent])] = {"QB-4"}
    welds[id(cache[retest])] = {"QB-5"}
    pulled, refused = _pull(_mode(settings, "strict"), cache,
                            _records(cache, [retest], settings))
    assert pulled == []
    assert refused == [(parent.name, "çarpaz-ay valideyn U-UT-26-010 gətirilmədi "
                                     "(U-UT-26-010R1): tikiş QB-4 ≠ QB-5")]


def test_strict_pulls_a_parent_that_inspected_every_retest_weld(
        tmp_path, settings, welds):
    cache, parent, retest = _one_retest(tmp_path)
    welds[id(cache[parent])] = {"W1", "W2", "W3"}
    welds[id(cache[retest])] = {"W2"}
    pulled, refused = _pull(_mode(settings, "strict"), cache,
                            _records(cache, [retest], settings))
    assert pulled == ["U-UT-26-010"]
    assert refused == []


def test_strict_never_falls_back_to_an_older_candidate(tmp_path, settings, welds):
    cache, parent, retest = _one_retest(tmp_path)
    older = _add(tmp_path, cache, "U-UT-26-010 (Platform)_en.docx",
                 "U-UT-26-010", "05.01.2026")
    welds[id(cache[parent])] = {"QB-4"}
    welds[id(cache[older])] = {"QB-5"}
    welds[id(cache[retest])] = {"QB-5"}
    pulled, refused = _pull(_mode(settings, "strict"), cache,
                            _records(cache, [retest], settings))
    assert pulled == []
    assert [name for name, _ in refused] == [parent.name]


def test_strict_without_welds_pulls_when_job_standard_and_item_match(
        tmp_path, settings, welds):
    cache, _parent, retest = _one_retest(tmp_path)
    pulled, refused = _pull(_mode(settings, "strict"), cache,
                            _records(cache, [retest], settings))
    assert pulled == ["U-UT-26-010"]
    assert refused == []


@pytest.mark.parametrize("kw, label", [
    (dict(parent_name="U-UT-26-010.docx"), "iş"),
    (dict(parent_kw={"standard": "ASME B31.3"}), "standart"),
    (dict(parent_kw={"item": "Flange"}), "item"),
])
def test_strict_without_welds_refuses_when_any_secondary_evidence_differs(
        tmp_path, settings, welds, kw, label):
    cache, parent, retest = _one_retest(tmp_path, **kw)
    pulled, refused = _pull(_mode(settings, "strict"), cache,
                            _records(cache, [retest], settings))
    assert pulled == []
    assert len(refused) == 1
    assert refused[0][1].split(": ", 1)[1].startswith(f"tikiş oxunmadı; {label} ")


def test_welds_on_one_side_only_fall_back_to_the_secondary_evidence(
        tmp_path, settings, welds):
    cache, parent, retest = _one_retest(tmp_path, parent_kw={"item": "Flange"})
    welds[id(cache[retest])] = {"QB-5"}
    pulled, refused = _pull(_mode(settings, "strict"), cache,
                            _records(cache, [retest], settings))
    assert pulled == []
    assert "tikiş oxunmadı; item" in refused[0][1]


def test_off_pulls_the_mismatched_parent_as_before(tmp_path, settings, welds):
    cache, parent, retest = _one_retest(tmp_path, parent_kw={"item": "Flange"})
    welds[id(cache[parent])] = {"QB-4"}
    welds[id(cache[retest])] = {"QB-5"}
    pulled, refused = _pull(_mode(settings, "off"), cache,
                            _records(cache, [retest], settings))
    assert pulled == ["U-UT-26-010"]
    assert refused == []


def test_the_refusal_reaches_report_skipped_and_the_retest_stays(
        tmp_path, settings, welds):
    cache, parent, retest = _one_retest(tmp_path)
    for n in range(1, 6):   # keep the group above min_total_client_volume
        _add(tmp_path, cache, f"U-UT-26-{n:03d} (Platform).docx",
             f"U-UT-26-{n:03d}", "15.05.2026")
    welds[id(cache[parent])] = {"QB-4"}
    welds[id(cache[retest])] = {"QB-5"}
    settings.input_dir = str(tmp_path)
    report = build_monthly_report(_mode(settings, "strict"), _Translator(),
                                  method="UT", client_code="UBOC", cache=cache)
    assert report.pulled_parents == 0
    assert "U-UT-26-010R1" in [r.report_no for r in report.rows]
    assert (parent.name, "çarpaz-ay valideyn U-UT-26-010 gətirilmədi "
                         "(U-UT-26-010R1): tikiş QB-4 ≠ QB-5") in report.skipped


def test_source_path_is_internal_only(tmp_path, settings):
    cache, _parent, retest = _one_retest(tmp_path)
    row = _records(cache, [retest], settings)[0]
    assert row.source_path == retest
    assert "source_path" not in repr(row)
