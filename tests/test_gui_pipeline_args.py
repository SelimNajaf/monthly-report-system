"""The GUI-to-backend argument seam for a scoped run.

Three links in the chain, tested without standing up a window:

* ``main_window._filter_args`` — dashboard filters -> ``--month/--method/--client``,
  the shared helper that makes "Run Pipeline" and "Start Portal Upload" scope
  identically.
* ``main_window._upload_args`` — that scope plus the Uploader page's run mode,
  limit, slow-motion and force, as ``uploader.py`` argv.
* ``worker_entry._run_pipeline`` — forwards that argv into ``main.main``.
"""

from __future__ import annotations

import io
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import main
from monthly_report.gui import worker_entry
from monthly_report.gui.services import catalog as catalog_mod
from monthly_report.gui.services.job_runner import (MODE_DRY, MODE_FILL,
                                                    MODE_LIVE, UploadOptions)
from monthly_report.gui.ui.main_window import _filter_args, _upload_args


class TestFilterArgs:
    def test_all_dimensions_selected(self):
        assert _filter_args("2025-06", "UT", "UBOC") == [
            "--month", "2025-06", "--method", "UT", "--client", "UBOC"]

    def test_all_on_all_omits_every_flag(self):
        # catalog.ALL is the empty string the dropdowns hand back for "All …".
        assert catalog_mod.ALL == ""
        assert _filter_args(catalog_mod.ALL, catalog_mod.ALL, catalog_mod.ALL) == []

    def test_partial_selection(self):
        assert _filter_args("2025-06", "", "") == ["--month", "2025-06"]
        assert _filter_args("", "UT", "") == ["--method", "UT"]

    def test_upload_scopes_with_the_same_helper(self):
        """The uploader argv is its own flags plus the shared scope, unchanged.

        Goes through _upload_args rather than rebuilding the prefix by hand: a
        test that reassembles what it is checking cannot fail when the real
        assembly changes, which is the only thing it exists to notice.
        """
        assert _upload_args(UploadOptions(), "2025-06", "UT", "") == [
            "--dry-run", "--all", "--month", "2025-06", "--method", "UT"]


class TestUploadArgs:
    """The Uploader page's four controls, as uploader.py argv."""

    def test_dry_run_is_the_default(self):
        assert _upload_args(UploadOptions(), "", "", "") == ["--dry-run", "--all"]

    def test_fill_only_passes_neither_dry_run_nor_live(self):
        """The third mode is the absence of both flags, not a variant of either.

        Without --dry-run a real browser opens; without --live nothing is saved.
        That combination is what leaves a filled form on screen to be read.
        """
        args = _upload_args(UploadOptions(mode=MODE_FILL), "", "", "")
        assert args == ["--all"]
        assert "--dry-run" not in args and "--live" not in args

    def test_live_asks_for_live(self):
        args = _upload_args(UploadOptions(mode=MODE_LIVE), "", "", "")
        assert args[:2] == ["--live", "--all"]

    def test_the_scope_comes_straight_after_the_mode_flags(self):
        assert _upload_args(UploadOptions(mode=MODE_LIVE), "FEB_2026", "MT", "KHF") == [
            "--live", "--all", "--month", "FEB_2026", "--method", "MT",
            "--client", "KHF", "--limit", "1"]

    def test_limit_is_sent_only_when_the_run_can_save(self):
        """--limit outside live would be a promise uploader.py has already broken.

        _effective_limit caps a run without --live at one report whatever the
        flag says (uploader.py:1985-1990), so printing --limit 3 on a fill-only
        run would describe a batch that is not going to happen.
        """
        options = UploadOptions(limit=3)
        for mode in (MODE_DRY, MODE_FILL):
            assert "--limit" not in _upload_args(
                UploadOptions(mode=mode, limit=3), "", "", "")
        assert _upload_args(UploadOptions(mode=MODE_LIVE, limit=3), "", "", "")[-2:] == [
            "--limit", "3"]
        assert options.limit == 3        # the helper does not mutate its input

    def test_slow_motion_needs_a_browser_to_slow(self):
        assert "--slow" not in _upload_args(
            UploadOptions(mode=MODE_DRY, slow=2000), "", "", "")
        for mode in (MODE_FILL, MODE_LIVE):
            assert "--slow" in _upload_args(UploadOptions(mode=mode, slow=2000), "", "", "")

    def test_slow_motion_at_zero_is_not_passed_at_all(self):
        """Zero is uploader.py's own default; sending it is noise in the console."""
        assert "--slow" not in _upload_args(UploadOptions(mode=MODE_FILL, slow=0), "", "", "")

    def test_force_applies_in_every_mode(self):
        """--force is a ledger decision, and the dry run keeps a ledger too."""
        for mode in (MODE_DRY, MODE_FILL, MODE_LIVE):
            assert "--force" in _upload_args(
                UploadOptions(mode=mode, force=True), "", "", "")

    def test_force_is_absent_unless_asked_for(self):
        for mode in (MODE_DRY, MODE_FILL, MODE_LIVE):
            assert "--force" not in _upload_args(UploadOptions(mode=mode), "", "", "")

    def test_every_mode_is_accepted_by_the_uploader_parser(self):
        """The flags are real flags — pinned against uploader's own argparse.

        Cheap insurance against the two drifting: a renamed flag here would
        otherwise surface as a child process exiting 2 on a live click.
        """
        import uploader

        parser = uploader.build_parser()
        for mode in (MODE_DRY, MODE_FILL, MODE_LIVE):
            args = _upload_args(
                UploadOptions(mode=mode, limit=3, slow=2000, force=True),
                "FEB_2026", "MT", "KHF")
            parsed = parser.parse_args(args)
            assert parsed.all and parsed.force
            assert parsed.dry_run == (mode == MODE_DRY)
            assert parsed.live == (mode == MODE_LIVE)

    def test_a_live_batch_survives_the_round_trip_to_effective_limit(self):
        """--limit 3 on a live run really does mean three reports."""
        import uploader

        args = _upload_args(UploadOptions(mode=MODE_LIVE, limit=3), "", "", "")
        assert uploader._effective_limit(uploader.build_parser().parse_args(args)) == 3

    def test_the_live_command_line_cannot_hang_on_the_confirmation_prompt(
            self, monkeypatch):
        """uploader.py asks before every save on a --live --all batch. This runs it
        as a child process with piped stdio, where that question would be invisible
        and unanswerable — so the prompt must disable itself on a pipe.

        Pinned against the real argv builder rather than a hand-written imitation:
        a future flag added here is exactly what would reintroduce the hang.
        """
        import sys

        import uploader

        monkeypatch.setattr(sys, "stdin", io.StringIO())    # what a pipe looks like
        argv = _upload_args(UploadOptions(mode=MODE_LIVE, limit=3), "", "", "")
        args = uploader.build_parser().parse_args(argv)

        assert not uploader._interactive_enabled(args)
        assert uploader._effective_limit(args, 12) == 3, (
            "an unattended GUI run keeps the cap it was given")


class TestWorkerForwarding:
    def test_pipeline_args_reach_main(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(main, "main", lambda argv=None: captured.update(argv=argv) or 0)

        code = worker_entry.run_worker(["pipeline", "--month", "JUN_2025", "--method", "UT"])

        assert code == 0
        assert captured["argv"] == ["--month", "JUN_2025", "--method", "UT"]

    def test_unscoped_pipeline_forwards_empty_argv(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(main, "main", lambda argv=None: captured.update(argv=argv) or 0)
        worker_entry.run_worker(["pipeline"])
        assert captured["argv"] == []
