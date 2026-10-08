"""The LAN network-share discovery scanner must map a tree read-only and never
crash on an offline root.

``discover_network_share.py`` traverses the configured UNC roots read-only and
emits an audit report. Three things are pinned here:

* ``normalize_unc`` — pure UNC/path string canonicalisation (mixed separators,
  trailing slash, preserved ``\\\\host\\share`` lead), tested with no network.
* ``scan_root`` / ``discover`` — mocked against a real ``tmp_path`` tree standing
  in for the share (works on local paths exactly as on a UNC one): file counts,
  extension split, year/client/extra-folder detection, twin ``.pdf``/``.docx``
  pair counting.
* Graceful offline — ``scan_root`` on a non-existent path returns
  ``reachable=False`` instead of raising, so one dead root never fails the run.

No live share is touched: every filesystem assertion runs against ``tmp_path``.
"""

from __future__ import annotations

import pytest

import discover_network_share as dns


# --- normalize_unc (pure) ---------------------------------------------------------------


class TestNormalizeUnc:
    @pytest.mark.parametrize("raw, expected", [
        # UNC lead preserved, forward slashes folded to backslash.
        ("//lan-host/Shared Docs/UT", r"\\lan-host\Shared Docs\UT"),
        (r"\\lan-host\Shared Docs\UT", r"\\lan-host\Shared Docs\UT"),
        # Trailing separator stripped.
        ("\\\\host\\share\\Method\\", r"\\host\share\Method"),
        # Repeated inner separators squeezed.
        ("\\\\host\\share\\\\Method", r"\\host\share\Method"),
        # Mixed separators normalised.
        ("\\\\host/share\\Method/Year", r"\\host\share\Method\Year"),
        # Already clean is a no-op.
        (r"\\host\share", r"\\host\share"),
    ])
    def test_normalises(self, raw, expected):
        assert dns.normalize_unc(raw) == expected

    def test_none_and_blank(self):
        assert dns.normalize_unc(None) == ""
        assert dns.normalize_unc("   ") == ""

    def test_local_path_has_no_unc_lead(self):
        # A non-UNC path must not gain a leading "\\".
        assert not dns.normalize_unc("C:/tmp/x").startswith("\\\\")


# --- is_year_folder / find_twin_pairs (pure) --------------------------------------------


class TestPureHelpers:
    @pytest.mark.parametrize("name", ["DP-2026", "RT-2026", "2005-2026", "FC-2019"])
    def test_year_folder_true(self, name):
        assert dns.is_year_folder(name) is True

    @pytest.mark.parametrize("name", ["UBOC", "Report", "", "AZFEN"])
    def test_year_folder_false(self, name):
        assert dns.is_year_folder(name) is False

    def test_find_twin_pairs_case_insensitive(self):
        names = ["U-UT-26-001.docx", "U-UT-26-001.PDF",
                 "U-UT-26-002.docx", "U-UT-26-003.pdf"]
        # Only 001 exists as both formats.
        assert dns.find_twin_pairs(names) == ["u-ut-26-001"]

    def test_find_twin_pairs_none(self):
        assert dns.find_twin_pairs(["a.docx", "b.pdf"]) == []


# --- scan_root / discover (mocked share under tmp_path) ---------------------------------


def _make_share(tmp_path):
    """Build a fake Method/Year/Client tree with a twin pair and a nested Report/."""
    method = tmp_path / "UT"
    client = method / "UT-2026" / "UBOC"
    client.mkdir(parents=True)
    # A twin (.docx + .pdf) plus a docx-only report = 3 doc files, 1 twin pair.
    (client / "U-UT-26-001.docx").write_text("x", encoding="utf-8")
    (client / "U-UT-26-001.pdf").write_bytes(b"%PDF-1.4 mock")
    (client / "U-UT-26-002.docx").write_text("y", encoding="utf-8")
    # A non-report file lands in the "other" bucket.
    (client / "notes.txt").write_text("z", encoding="utf-8")
    # An extra nested folder deeper than Method/Year/Client.
    extra = client / "Report"
    extra.mkdir()
    (extra / "U-UT-26-001-scan.pdf").write_bytes(b"%PDF-1.4 scan")
    return method


class TestScanRoot:
    def test_maps_counts_and_structure(self, tmp_path):
        method = _make_share(tmp_path)
        scan = dns.scan_root(method)

        assert scan.reachable is True
        # 3 doc files under client + 1 under Report/ = 4 docs; +1 txt = 5 total.
        assert scan.total_files == 5
        assert scan.docx == 2
        assert scan.pdf == 2
        assert scan.ext_counts.get("other") == 1
        assert scan.total_bytes > 0
        assert scan.newest_mtime is not None

    def test_detects_year_client_and_extra_folders(self, tmp_path):
        method = _make_share(tmp_path)
        scan = dns.scan_root(method)

        assert "UT-2026" in scan.year_folders
        assert "UBOC" in scan.client_folders
        assert "Report" in scan.extra_folders

    def test_counts_twin_pairs(self, tmp_path):
        method = _make_share(tmp_path)
        scan = dns.scan_root(method)

        # Exactly one stem (U-UT-26-001) exists as both .docx and .pdf in the
        # client folder. The Report/ scan.pdf is a different stem, no twin there.
        assert scan.twin_pairs == 1

    def test_tree_records_method_year_client(self, tmp_path):
        method = _make_share(tmp_path)
        scan = dns.scan_root(method)

        leaf = scan.tree["UT"]["UT-2026"]["UBOC"]
        # 3 docs directly under UBOC + 1 in the nested Report/ (still UBOC's client)
        # = 4; deeper nesting collapses into the owning client leaf.
        assert leaf["count"] == 4
        assert any("U-UT-26-001" in fn for fn in leaf["sample"])


class TestOffline:
    def test_missing_path_is_unreachable_not_raising(self, tmp_path):
        scan = dns.scan_root(tmp_path / "does-not-exist")
        assert scan.reachable is False
        assert scan.error
        assert scan.total_files == 0

    def test_discover_survives_mixed_reachability(self, tmp_path):
        method = _make_share(tmp_path)
        # timeout=None keeps the local tmp_path scan on the calling thread.
        result = dns.discover([str(method), str(tmp_path / "offline-root")],
                              timeout=None)

        assert len(result.roots) == 2
        assert len(result.reachable_roots) == 1
        assert result.total_files == 5
        assert result.total_twins == 1

    def test_reachability_probe_times_out_instead_of_hanging(self, monkeypatch,
                                                             tmp_path):
        # A hung SMB negotiation: the probe never answers. scan_root_bounded must
        # short-circuit to an unreachable "timeout" root, never block the run.
        monkeypatch.setattr(dns, "_reachable_within", lambda root, timeout: None)
        scan = dns.scan_root_bounded(tmp_path, "\\\\host\\share\\X", timeout=0.2)

        assert scan.reachable is False
        assert "timeout" in scan.error

    def test_reachable_root_scans_fully_despite_bound(self, tmp_path):
        # Reachable share with a live bound: the probe passes, then the full walk
        # runs to completion (files are NOT truncated by the probe timeout).
        method = _make_share(tmp_path)
        scan = dns.scan_root_bounded(method, str(method), timeout=5.0)

        assert scan.reachable is True
        assert scan.total_files == 5
        assert scan.twin_pairs == 1


# --- render_markdown --------------------------------------------------------------------


class TestRenderMarkdown:
    def test_report_contains_headings_and_figures(self, tmp_path):
        method = _make_share(tmp_path)
        result = dns.discover([str(method), str(tmp_path / "offline-root")])
        md = dns.render_markdown(result)

        assert "# LAN Network Share" in md
        assert "## 1. Summary" in md
        assert "## 2. Structure Tree" in md
        assert "## 3. Identified Edge Cases" in md
        assert "## 4. Proposed Automated Staging Strategy" in md
        # Twin-pair figure and the offline root both surface.
        assert "Twin `.pdf`/`.docx` pairs: **1**" in md
        assert "offline" in md.lower()

    def test_all_offline_still_renders(self, tmp_path):
        result = dns.discover([str(tmp_path / "a"), str(tmp_path / "b")])
        md = dns.render_markdown(result)
        assert "every configured root was unreachable" in md
