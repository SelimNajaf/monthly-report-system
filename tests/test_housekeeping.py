"""Self-healing input housekeeping: dedup, UnSorted prune, quarantine purge.

Three passes clean ``input/``, and every one of them removes a file — so the
tests here are weighted towards what must *survive*. The invariant that matters
is that a prune is only ever justified by a proven byte-identical survivor
(or, for quarantine, a parsed-and-sorted twin), and that "prune" means moved to
``input/_PRUNED/``, never deleted.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from monthly_report import pre_processor as pp
from monthly_report.naming import PDF_ARCHIVE_DIR, PRUNED_DIR, QUARANTINE_DIR

# Registry mirroring settings.yaml's shape: code -> {folder, patterns}.
_RAW = {"ndt_methods": {
    "UT": {"folder": "UT", "patterns": ["-UT-"]},
    "RT": {"folder": "RT", "patterns": ["-RT-"]},
    "MT": {"folder": "MPI", "patterns": ["-MT-"]},
}}


def _settings(tmp_path: Path):
    return SimpleNamespace(input_dir=tmp_path, raw=_RAW, dayfirst=True)


def _write(root: Path, rel: str, body: str) -> Path:
    """Create input/<rel> with ``body`` as its bytes. Returns the path."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _pruned_names(root: Path) -> set[str]:
    trash = root / PRUNED_DIR
    return {p.name for p in trash.iterdir()} if trash.is_dir() else set()


# --------------------------------------------------------------------------- #
# Duplicate .docx pruning — SHA-256, keep the cleanest name
# --------------------------------------------------------------------------- #
class TestPruneDuplicateDocx:
    def test_keeps_bare_name_prunes_en_suffixed_twins(self, tmp_path):
        _write(tmp_path, "RT/KF-RT-26-070.docx", "same bytes")
        _write(tmp_path, "RT/KF-RT-26-070_en.docx", "same bytes")
        _write(tmp_path, "RT/KF-RT-26-070_en_en.docx", "same bytes")

        pruned = pp.prune_duplicate_docx(_settings(tmp_path))

        assert (tmp_path / "RT/KF-RT-26-070.docx").exists()          # cleanest survives
        assert not (tmp_path / "RT/KF-RT-26-070_en.docx").exists()
        assert not (tmp_path / "RT/KF-RT-26-070_en_en.docx").exists()
        assert {name for name, _keeper in pruned} == {
            "KF-RT-26-070_en.docx", "KF-RT-26-070_en_en.docx"}
        assert all(keeper == "KF-RT-26-070.docx" for _n, keeper in pruned)

    def test_pruned_files_are_recoverable_not_deleted(self, tmp_path):
        _write(tmp_path, "RT/KF-RT-26-070.docx", "same bytes")
        _write(tmp_path, "RT/KF-RT-26-070_en.docx", "same bytes")

        pp.prune_duplicate_docx(_settings(tmp_path))

        trash = tmp_path / PRUNED_DIR / "KF-RT-26-070_en.docx"
        assert trash.exists()
        assert trash.read_text(encoding="utf-8") == "same bytes"     # intact, restorable

    def test_copy_marker_loses_to_bare_name(self, tmp_path):
        _write(tmp_path, "UT/U-UT-26-010.docx", "body")
        _write(tmp_path, "UT/U-UT-26-010 (1).docx", "body")

        pp.prune_duplicate_docx(_settings(tmp_path))

        assert (tmp_path / "UT/U-UT-26-010.docx").exists()
        assert not (tmp_path / "UT/U-UT-26-010 (1).docx").exists()

    def test_mid_name_job_number_is_not_a_copy_marker(self, tmp_path):
        """Real names carry job numbers in parentheses — only a TRAILING (N) is a copy."""
        _write(tmp_path, "MPI/KF-MT-26-001 (2165)  (EEMUA 158).docx", "body")
        _write(tmp_path, "MPI/KF-MT-26-001 (2165)  (EEMUA 158)_en_en.docx", "body")

        pruned = pp.prune_duplicate_docx(_settings(tmp_path))

        # The job-numbered original wins on _en count; neither is a "copy".
        assert (tmp_path / "MPI/KF-MT-26-001 (2165)  (EEMUA 158).docx").exists()
        assert [n for n, _k in pruned] == ["KF-MT-26-001 (2165)  (EEMUA 158)_en_en.docx"]

    def test_different_content_is_never_pruned(self, tmp_path):
        """Same report key, different bytes — two real files. Both stay."""
        _write(tmp_path, "RT/KF-RT-26-070.docx", "revision A")
        _write(tmp_path, "RT/KF-RT-26-070_en.docx", "revision B")

        pruned = pp.prune_duplicate_docx(_settings(tmp_path))

        assert pruned == []
        assert (tmp_path / "RT/KF-RT-26-070.docx").exists()
        assert (tmp_path / "RT/KF-RT-26-070_en.docx").exists()

    def test_sorted_copy_wins_over_identical_loose_copy(self, tmp_path):
        """A cleaner NAME must not drag the prune onto the correctly-sorted file."""
        _write(tmp_path, "RT/KF-RT-26-070_en.docx", "dup")         # sorted, uglier name
        _write(tmp_path, "UnSorted/KF-RT-26-070.docx", "dup")      # loose, cleaner name

        pp.prune_duplicate_docx(_settings(tmp_path))

        assert (tmp_path / "RT/KF-RT-26-070_en.docx").exists()     # sorted copy survives
        assert not (tmp_path / "UnSorted/KF-RT-26-070.docx").exists()

    @pytest.mark.parametrize("settled", [QUARANTINE_DIR, PDF_ARCHIVE_DIR, PRUNED_DIR])
    def test_settled_dirs_are_never_scanned(self, tmp_path, settled):
        """A twin parked in archive/quarantine/trash must not be pruned NOR win the keep."""
        _write(tmp_path, "RT/KF-RT-26-070.docx", "dup")
        _write(tmp_path, f"{settled}/KF-RT-26-070.docx", "dup")

        pruned = pp.prune_duplicate_docx(_settings(tmp_path))

        assert pruned == []
        assert (tmp_path / "RT/KF-RT-26-070.docx").exists()
        assert (tmp_path / settled / "KF-RT-26-070.docx").exists()

    def test_unique_files_untouched_and_pass_is_idempotent(self, tmp_path):
        _write(tmp_path, "RT/KF-RT-26-070.docx", "one")
        _write(tmp_path, "UT/U-UT-26-010.docx", "two")

        assert pp.prune_duplicate_docx(_settings(tmp_path)) == []
        assert pp.prune_duplicate_docx(_settings(tmp_path)) == []   # converges
        assert not (tmp_path / PRUNED_DIR).exists()


# --------------------------------------------------------------------------- #
# UnSorted redundancy pruning — only when proven settled elsewhere
# --------------------------------------------------------------------------- #
class TestPruneUnsortedRedundant:
    def test_docx_already_sorted_is_pruned(self, tmp_path):
        _write(tmp_path, "RT/KF-RT-26-070.docx", "report body")
        _write(tmp_path, "UnSorted/KF-RT-26-070.docx", "report body")

        pruned = pp.prune_unsorted_redundant(_settings(tmp_path))

        assert not (tmp_path / "UnSorted/KF-RT-26-070.docx").exists()
        assert (tmp_path / "RT/KF-RT-26-070.docx").exists()
        assert pruned == [("KF-RT-26-070.docx", "RT/KF-RT-26-070.docx")]

    def test_pdf_already_archived_is_pruned(self, tmp_path):
        _write(tmp_path, f"{PDF_ARCHIVE_DIR}/U-UT-26-010.pdf", "%PDF bytes")
        _write(tmp_path, "UnSorted/U-UT-26-010.pdf", "%PDF bytes")

        pruned = pp.prune_unsorted_redundant(_settings(tmp_path))

        assert not (tmp_path / "UnSorted/U-UT-26-010.pdf").exists()
        assert [n for n, _w in pruned] == ["U-UT-26-010.pdf"]

    def test_nested_client_folders_are_walked(self, tmp_path):
        _write(tmp_path, "UT/U-UT-26-010.docx", "body")
        _write(tmp_path, "UnSorted/KHAZAR/U-UT-26-010.docx", "body")

        pp.prune_unsorted_redundant(_settings(tmp_path))

        assert not (tmp_path / "UnSorted/KHAZAR/U-UT-26-010.docx").exists()

    def test_same_name_different_content_is_kept(self, tmp_path):
        """The name-clash leftover sort couldn't place. A human must look at it."""
        _write(tmp_path, "RT/KF-RT-26-070.docx", "the sorted one")
        _write(tmp_path, "UnSorted/KF-RT-26-070.docx", "a DIFFERENT report")

        pruned = pp.prune_unsorted_redundant(_settings(tmp_path))

        assert pruned == []
        assert (tmp_path / "UnSorted/KF-RT-26-070.docx").exists()

    def test_unsettled_file_is_kept(self, tmp_path):
        _write(tmp_path, "UnSorted/BRAND-NEW-26-001.docx", "never seen")
        assert pp.prune_unsorted_redundant(_settings(tmp_path)) == []
        assert (tmp_path / "UnSorted/BRAND-NEW-26-001.docx").exists()

    def test_quarantined_twin_does_not_justify_a_prune(self, tmp_path):
        """Settled means sorted or archived — NOT quarantined."""
        _write(tmp_path, f"{QUARANTINE_DIR}/KF-RT-26-070.docx", "body")
        _write(tmp_path, "UnSorted/KF-RT-26-070.docx", "body")

        assert pp.prune_unsorted_redundant(_settings(tmp_path)) == []
        assert (tmp_path / "UnSorted/KF-RT-26-070.docx").exists()

    def test_no_unsorted_dir_is_a_noop(self, tmp_path):
        _write(tmp_path, "RT/KF-RT-26-070.docx", "body")
        assert pp.prune_unsorted_redundant(_settings(tmp_path)) == []


# --------------------------------------------------------------------------- #
# Quarantine self-healing — retire copies a searchable report has replaced
# --------------------------------------------------------------------------- #
class TestPurgeReplacedQuarantine:
    def test_purged_once_a_searchable_copy_is_parsed_and_sorted(self, tmp_path):
        _write(tmp_path, f"{QUARANTINE_DIR}/KF-RT-26-070.docx", "old scanned image")
        active = _write(tmp_path, "RT/KF-RT-26-070.docx", "fresh searchable text")
        cache = {active: ["parsed blocks"]}

        purged = pp.purge_replaced_quarantine(_settings(tmp_path), cache)

        assert purged == ["KF-RT-26-070.docx"]
        assert not (tmp_path / QUARANTINE_DIR / "KF-RT-26-070.docx").exists()
        assert (tmp_path / PRUNED_DIR / "KF-RT-26-070.docx").exists()   # recoverable
        assert active.exists()

    def test_suffixed_quarantine_name_still_matches_by_report_key(self, tmp_path):
        _write(tmp_path, f"{QUARANTINE_DIR}/KF-RT-26-070_en_en.docx", "old image")
        active = _write(tmp_path, "RT/KF-RT-26-070.docx", "searchable")

        purged = pp.purge_replaced_quarantine(_settings(tmp_path), {active: []})

        assert purged == ["KF-RT-26-070_en_en.docx"]

    def test_unresolved_quarantine_is_left_alone(self, tmp_path):
        """No searchable twin -> still unresolved -> must stay in quarantine."""
        _write(tmp_path, f"{QUARANTINE_DIR}/KF-RT-26-099.docx", "still unreadable")
        active = _write(tmp_path, "RT/KF-RT-26-070.docx", "unrelated report")

        purged = pp.purge_replaced_quarantine(_settings(tmp_path), {active: []})

        assert purged == []
        assert (tmp_path / QUARANTINE_DIR / "KF-RT-26-099.docx").exists()

    def test_replacement_that_did_not_parse_does_not_purge(self, tmp_path):
        """On disk in RT/ but absent from the cache = it failed to parse. Not a heal."""
        _write(tmp_path, f"{QUARANTINE_DIR}/KF-RT-26-070.docx", "old image")
        _write(tmp_path, "RT/KF-RT-26-070.docx", "also unreadable")

        purged = pp.purge_replaced_quarantine(_settings(tmp_path), {})

        assert purged == []
        assert (tmp_path / QUARANTINE_DIR / "KF-RT-26-070.docx").exists()

    def test_parsed_but_still_loose_replacement_does_not_purge(self, tmp_path):
        """Not yet in a method folder -> not 'placed into its active sorted directory'."""
        _write(tmp_path, f"{QUARANTINE_DIR}/KF-RT-26-070.docx", "old image")
        loose = _write(tmp_path, "UnSorted/KF-RT-26-070.docx", "searchable but unsorted")

        purged = pp.purge_replaced_quarantine(_settings(tmp_path), {loose: []})

        assert purged == []
        assert (tmp_path / QUARANTINE_DIR / "KF-RT-26-070.docx").exists()

    def test_asr_is_never_healed_away_by_its_ordinary_twin(self, tmp_path):
        """An ASR shares its report token with the ordinary report of the same number.

        It sits in quarantine because ASR/ARS is excluded pipeline-wide, not because
        it was unreadable — so the active twin is a *different document*, not a
        searchable replacement. Regression: this fired on the real input tree.
        """
        _write(tmp_path, f"{QUARANTINE_DIR}/KF-RT-26-053R1 ASR (KF 2123).docx", "asr doc")
        active = _write(tmp_path, "RT/KF-RT-26-053R1.docx", "the ordinary report")

        purged = pp.purge_replaced_quarantine(_settings(tmp_path), {active: []})

        assert purged == []
        assert (tmp_path / QUARANTINE_DIR / "KF-RT-26-053R1 ASR (KF 2123).docx").exists()

    def test_no_quarantine_dir_is_a_noop(self, tmp_path):
        active = _write(tmp_path, "RT/KF-RT-26-070.docx", "body")
        assert pp.purge_replaced_quarantine(_settings(tmp_path), {active: []}) == []


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
class TestHashAndRank:
    def test_sha256_matches_on_identical_bytes_only(self, tmp_path):
        a = _write(tmp_path, "a.docx", "same")
        b = _write(tmp_path, "b.docx", "same")
        c = _write(tmp_path, "c.docx", "different")
        assert pp._sha256(a) == pp._sha256(b) != pp._sha256(c)

    def test_sha256_of_unreadable_file_is_none(self, tmp_path):
        """A file we cannot hash is a file we must not prune."""
        assert pp._sha256(tmp_path / "does-not-exist.docx") is None

    def test_keeper_rank_orders_cleanest_first(self, tmp_path):
        names = ["RT/KF-RT-26-070_en_en.docx", "RT/KF-RT-26-070.docx",
                 "RT/KF-RT-26-070 (1).docx", "RT/KF-RT-26-070_en.docx"]
        paths = [_write(tmp_path, n, "x") for n in names]
        folders = pp._method_folders(_settings(tmp_path))
        best = min(paths, key=lambda p: pp._keeper_rank(p, folders, tmp_path))
        assert best.name == "KF-RT-26-070.docx"

    def test_method_folders_reads_the_registry_folder_field(self, tmp_path):
        # MT maps to the MPI folder — the code, not the folder, is the registry key.
        assert pp._method_folders(_settings(tmp_path)) == {"ut", "rt", "mpi"}

    def test_settled_dirs_covers_archive_quarantine_and_trash(self):
        assert pp.SETTLED_DIRS == {PDF_ARCHIVE_DIR.casefold(),
                                   QUARANTINE_DIR.casefold(), PRUNED_DIR.casefold()}

    def test_dashboard_document_count_excludes_the_same_dirs(self):
        """metrics._EXCLUDED promises to mirror SETTLED_DIRS — pin it so a new
        settled folder can never silently inflate the Documents card."""
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from monthly_report.gui.services import metrics

        assert metrics._EXCLUDED == set(pp.SETTLED_DIRS)
