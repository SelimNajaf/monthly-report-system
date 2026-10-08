"""Pin ``network_ingestion.stage_size_mismatch`` and the ``delete`` folder rule (R3-B).

The ABSENT branch of :func:`sync_from_lan` skips a share file whose STEM already
exists under ``input/`` — without comparing content. A same-named file whose bytes
differ (a re-signed report, a corrected scan) was never staged, and the registry
then remembered it as unchanged, so it never came back.

* Default ``false``: exactly the old behaviour.
* ``true``: a share file whose exact NAME exists locally but whose SIZE differs
  from every local copy of that name is staged as a ``-lan`` twin; the existing
  hash dedup then decides. An equal size is skipped as before.
* A file under a folder named ``delete`` (any case) is never staged, under either
  value of the key.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from monthly_report.services import network_ingestion as ni
from tests.test_network_ingestion import _settings, _unsorted_names, _write


def _with_key(settings, value):
    settings.raw["network_ingestion"]["stage_size_mismatch"] = value
    return settings


# --------------------------------------------------------------------------- #
# The reader


def test_key_defaults_to_false_and_only_true_turns_it_on(tmp_path):
    s = _settings(tmp_path, [])
    assert ni.stage_size_mismatch(s) is False
    for value, expected in ((True, True), (False, False), ("true", False), (1, False)):
        assert ni.stage_size_mismatch(_with_key(s, value)) is expected


def test_under_delete_folder_is_case_insensitive_and_segment_exact():
    assert ni.under_delete_folder(r"\\h\s\X-ray\RT-2026\UP\delete\UP-RT-26-043.docx")
    assert ni.under_delete_folder("share/UT/NOV/Delete/NOV-UTM-26-001.pdf")
    assert ni.under_delete_folder("share/DELETE/x/KF-RT-26-001.docx")
    assert not ni.under_delete_folder("share/deleted/KF-RT-26-001.docx")
    assert not ni.under_delete_folder("share/KHAZAR/delete-me.docx")


# --------------------------------------------------------------------------- #
# Default: unchanged


def _same_name_different_size(tmp_path):
    share = tmp_path / "share" / "X-ray"
    _write(share / "RT-2026" / "KHAZAR" / "KF-RT-26-070 (KF 2222).docx", b"share-bytes-longer")
    settings = _settings(tmp_path, [share])
    _write(settings.input_dir / "KHAZAR" / "KF-RT-26-070 (KF 2222).docx", b"local")
    return settings


def test_default_skips_a_same_name_file_as_before(tmp_path):
    settings = _same_name_different_size(tmp_path)

    result = ni.sync_from_lan(settings, "2026-08", timeout=None)

    assert result.staged == [] and result.skipped_dupes == 1
    assert _unsorted_names(settings) == []


def test_explicit_false_is_the_default(tmp_path):
    settings = _with_key(_same_name_different_size(tmp_path), False)
    result = ni.sync_from_lan(settings, "2026-08", timeout=None)
    assert result.staged == [] and result.skipped_dupes == 1


# --------------------------------------------------------------------------- #
# On


def test_size_difference_is_staged_as_a_lan_twin(tmp_path):
    settings = _with_key(_same_name_different_size(tmp_path), True)
    logs = []

    result = ni.sync_from_lan(settings, "2026-08", timeout=None, log=logs.append)

    assert result.staged == ["KF-RT-26-070 (KF 2222)-lan.docx"]
    assert _unsorted_names(settings) == ["KF-RT-26-070 (KF 2222)-lan.docx"]
    staged = settings.input_dir / "UnSorted" / "KF-RT-26-070 (KF 2222)-lan.docx"
    assert staged.read_bytes() == b"share-bytes-longer"
    # The local copy is untouched.
    assert (settings.input_dir / "KHAZAR" / "KF-RT-26-070 (KF 2222).docx"
            ).read_bytes() == b"local"
    assert any("same name, different size" in line for line in logs)


def test_a_file_the_registry_already_skipped_is_picked_up_when_the_key_turns_on(tmp_path):
    """The real case: an earlier run skipped it by name and fingerprinted it with
    no hash, so the registry calls it unchanged. The key must still reach it."""
    settings = _same_name_different_size(tmp_path)
    first = ni.sync_from_lan(settings, "2026-08", timeout=None)
    assert first.staged == []

    second = ni.sync_from_lan(_with_key(settings, True), "2026-08", timeout=None)
    third = ni.sync_from_lan(settings, "2026-08", timeout=None)

    assert second.staged == ["KF-RT-26-070 (KF 2222)-lan.docx"]
    assert third.staged == [] and third.unchanged == 1       # hash now recorded


def test_equal_size_is_skipped(tmp_path):
    share = tmp_path / "share" / "X-ray"
    _write(share / "RT-2026" / "KHAZAR" / "KF-RT-26-071.docx", b"AAAAA")
    settings = _with_key(_settings(tmp_path, [share]), True)
    _write(settings.input_dir / "KHAZAR" / "KF-RT-26-071.docx", b"BBBBB")

    result = ni.sync_from_lan(settings, "2026-08", timeout=None)

    assert result.staged == [] and result.skipped_dupes == 1


def test_other_extension_twin_only_is_not_a_size_mismatch(tmp_path):
    share = tmp_path / "share" / "X-ray"
    _write(share / "RT-2026" / "KHAZAR" / "KF-RT-26-072.pdf", b"pdf-bytes-long")
    settings = _with_key(_settings(tmp_path, [share]), True)
    _write(settings.input_dir / "KHAZAR" / "KF-RT-26-072.docx", b"docx")

    result = ni.sync_from_lan(settings, "2026-08", timeout=None)

    assert result.staged == [] and result.skipped_dupes == 1


def test_size_twin_identical_to_known_content_is_removed_by_the_hash_check(tmp_path):
    data = b"already-known-content"
    share = tmp_path / "share" / "X-ray"
    _write(share / "RT-2026" / "KHAZAR" / "KF-RT-26-073.docx", data)
    settings = _with_key(_settings(tmp_path, [share]), True)
    _write(settings.input_dir / "KHAZAR" / "KF-RT-26-073.docx", b"x")
    cache = tmp_path / ".parse_cache"
    cache.mkdir()
    (cache / f"{hashlib.sha256(data).hexdigest()}.json").write_text("{}", encoding="utf-8")

    result = ni.sync_from_lan(settings, "2026-08", timeout=None)

    assert result.staged == [] and result.skipped_dupes == 1
    assert _unsorted_names(settings) == []


def test_twin_tail_already_used_anywhere_is_not_reused(tmp_path):
    share = tmp_path / "share" / "X-ray"
    _write(share / "RT-2026" / "KHAZAR" / "KF-RT-26-074.docx", b"third-version!")
    settings = _with_key(_settings(tmp_path, [share]), True)
    _write(settings.input_dir / "KHAZAR" / "KF-RT-26-074.docx", b"one")
    _write(settings.input_dir / "KHAZAR" / "KF-RT-26-074-lan.docx", b"two!")

    result = ni.sync_from_lan(settings, "2026-08", timeout=None)

    assert result.staged == ["KF-RT-26-074-lan2.docx"]


def test_a_lan_twin_of_equal_size_counts_as_a_local_copy(tmp_path):
    share = tmp_path / "share" / "X-ray"
    _write(share / "RT-2026" / "KHAZAR" / "KF-RT-26-075.docx", b"12345")
    settings = _with_key(_settings(tmp_path, [share]), True)
    _write(settings.input_dir / "KHAZAR" / "KF-RT-26-075.docx", b"1")
    _write(settings.input_dir / "KHAZAR" / "KF-RT-26-075-lan.docx", b"abcde")

    result = ni.sync_from_lan(settings, "2026-08", timeout=None)

    assert result.staged == []


# --------------------------------------------------------------------------- #
# delete/ — never, under either value


def _delete_tree(tmp_path, folder):
    share = tmp_path / "share" / "X-ray"
    _write(share / "RT-2026" / "UNIPER-PROKON" / folder / "UP-RT-26-043.docx", b"new")
    _write(share / "RT-2026" / "SDLN" / folder / "SDLN-UTM-26-002.pdf", b"brand-new")
    return _settings(tmp_path, [share])


def test_delete_folder_is_never_staged_with_the_key_off(tmp_path):
    for folder in ("delete", "Delete", "DELETE"):
        settings = _delete_tree(tmp_path / folder, folder)
        result = ni.sync_from_lan(settings, "2026-08", timeout=None)
        assert result.staged == [] and result.checked == 0
        assert _unsorted_names(settings) == []


def test_delete_folder_is_never_staged_with_the_key_on(tmp_path):
    settings = _with_key(_delete_tree(tmp_path, "delete"), True)
    _write(settings.input_dir / "UNIPER-PROKON" / "UP-RT-26-043.docx", b"x")

    result = ni.sync_from_lan(settings, "2026-08", timeout=None)

    assert result.staged == [] and result.checked == 0
    assert _unsorted_names(settings) == []


def test_delete_filter_also_holds_for_a_root_inside_a_delete_folder(tmp_path):
    share = tmp_path / "delete" / "X-ray"
    _write(share / "RT-2026" / "KHAZAR" / "KF-RT-26-076.docx", b"bytes")
    settings = _with_key(_settings(tmp_path, [share]), True)

    result = ni.sync_from_lan(settings, "2026-08", timeout=None)

    assert result.staged == []
    assert not Path(settings.input_dir / "UnSorted").exists()


# --------------------------------------------------------------------------- #
# A -lan twin never carries its marker into the report number


def test_lan_tail_never_reaches_the_report_number():
    from monthly_report.docx_reader import parse_filename_metadata as meta
    assert meta("B-MT-26-001-lan.docx")["report_no"] == "B-MT-26-001"
    assert meta("B-MT-26-001-lan2.docx")["report_no"] == "B-MT-26-001"
    assert meta("B-MT-26-001_en-lan.docx")["report_no"] == "B-MT-26-001"
    assert meta("KF-RT-26-070 (KF 2222)-lan2.docx") == {
        "report_no": "KF-RT-26-070", "document_name": "KF-RT-26-070 (KF 2222)",
        "standard": None}
    # Real numbers are untouched (red line 2).
    assert meta("U-UT-25-003rej.docx")["report_no"] == "U-UT-25-003rej"
    assert meta("KF-MT-26-003 (2230) (ISO-23278)_en.docx")["report_no"] == "KF-MT-26-003"
    assert meta("KF-RT-26-lane.docx")["report_no"] == "KF-RT-26-lane"
