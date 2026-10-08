"""Characterization tests for report-number identity rules.

Expected values pinned from the pre-refactor merger.py/main.py behavior so the
structural split can be verified to preserve semantics exactly.
"""

from monthly_report import report_identity as ri


def test_report_key_normalizes_case_spaces_underscores():
    assert ri.report_key("kf-mt-26-001") == "KF-MT-26-001"
    assert ri.report_key(" KF-MT-26- 001 ") == "KF-MT-26-001"
    assert ri.report_key("KF_MT_26_001") == "KFMT26001"
    assert ri.report_key("") == ""
    assert ri.report_key(None) == ""


def test_strip_retest_removes_trailing_marker_only():
    assert ri.strip_retest("U-UT-26-005R1") == "U-UT-26-005"
    assert ri.strip_retest("U-UT-26-005RS1") == "U-UT-26-005"
    assert ri.strip_retest("U-UT-26-005RW") == "U-UT-26-005"
    assert ri.strip_retest("U-UT-26-005R1-1") == "U-UT-26-005"
    assert ri.strip_retest("U-UT-26-005") == "U-UT-26-005"
    # RT in the middle of a number is not a retest marker.
    assert ri.strip_retest("AZF-RT-W1-26-257") == "AZF-RT-W1-26-257"


def test_retest_rank():
    assert ri.retest_rank("U-UT-26-005") == 0
    assert ri.retest_rank("U-UT-26-005R1") == 1
    assert ri.retest_rank("U-UT-26-005R2") == 2
    assert ri.retest_rank("U-UT-26-005RS1") == 1
    assert ri.retest_rank("U-UT-26-005RW") == 1   # no digit -> first retest
    assert ri.retest_rank("") == 0


def test_is_excluded_asr_ars_case_insensitive():
    assert ri.is_excluded("KF-MT-26-005ASR (2162).docx", "")
    assert ri.is_excluded("kf-ut-26-001asr.docx", "")
    assert ri.is_excluded("", "KF-UT-26-001ARS")
    assert not ri.is_excluded("KF-MT-26-005 (2162).docx", "KF-MT-26-005")


def test_leading_token_cleans_sdln_noise():
    assert ri.leading_token("DP-SDLN-26-103___F1895___19.05.26.pdf") == "DP-SDLN-26-103"
    assert ri.leading_token("U-UT-26-001  (Platform).pdf") == "U-UT-26-001"
    assert ri.leading_token("U-UT-26-001  (Platform)_en_en.docx") == "U-UT-26-001"
    assert ri.leading_token("U-UTM-26-001_______F1945___.pdf") == "U-UTM-26-001"


def test_report_key_of_matches_twin_files():
    assert (ri.report_key_of("U-UT-26-001  (Platform).pdf")
            == ri.report_key_of("U-UT-26-001  (Platform)_en_en.docx")
            == "U-UT-26-001")


def test_squash_collapses_whitespace():
    assert ri.squash("  a \n b\t c ") == "a b c"
    assert ri.squash(None) == ""
