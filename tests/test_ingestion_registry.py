"""The O(1) ingestion registry and the incremental compile skip it feeds.

Two accelerators are pinned here, both built on the same idea — do not redo work whose
inputs did not move:

* **STAGE 0-LAN.** ``ingestion_registry`` remembers ``(unc_path, size, mtime, sha256)``
  for every share file already ingested. A repeat run answers "have I got this?" from
  local JSON, so an unchanged share costs one directory walk and **zero** bytes over
  SMB. The size/mtime pair is the point: it is carried by the ``os.scandir`` listing
  itself, while a content hash would need the very transfer being avoided. The pair
  also catches the case the old filename index could not see at all — a report EDITED
  on the share under its original name, which used to leave the local copy silently
  stale forever.
* **Group compilation.** A month+client group whose reports all sat still keeps
  its existing PDF + sidecar instead of re-rendering identical bytes.

The share is a local ``tmp_path`` tree (the walk is identical on a local path), so no
network is touched. The registry path is always passed in, so the real ``.state/`` is
never read or written.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from monthly_report import config
from monthly_report.services import ingestion_registry as reg
from monthly_report.services import network_ingestion as ni

_SETTINGS_YAML = Path(__file__).resolve().parents[1] / "config" / "settings.yaml"


# --- fixtures / builders ----------------------------------------------------------------


def _real_registries():
    """The LIVE ``clients`` + ``ndt_methods`` blocks — the filename gate is config-driven."""
    raw = config.load_settings(_SETTINGS_YAML).raw
    return raw.get("clients", {}), raw.get("ndt_methods", {})


def _settings(tmp_path, sources):
    """A minimal stand-in for config.Settings carrying only what the sync reads."""
    input_dir = tmp_path / "input"
    input_dir.mkdir(exist_ok=True)
    clients, ndt_methods = _real_registries()
    return SimpleNamespace(
        input_dir=input_dir,
        project_root=tmp_path,
        target_month="2026-08",
        raw={
            "network_ingestion": {"lan_sources": [str(s) for s in sources]},
            "performance": {"parse_cache_dir": ".parse_cache"},
            "clients": clients,
            "ndt_methods": ndt_methods,
        },
    )


def _write(path, data=b"report-bytes"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _sync(settings, tmp_path, **kwargs):
    """One STAGE 0-LAN run against the fake share, registry parked in tmp_path."""
    return ni.sync_from_lan(settings, "2026-08", timeout=None,
                            registry_path=tmp_path / ".state" / "manifest.json",
                            log=lambda _m: None, **kwargs)


def _local_names(settings):
    """Every staged report under input/, by name — the sync's visible output."""
    return sorted(p.name for p in Path(settings.input_dir).rglob("*")
                  if p.is_file())


@pytest.fixture
def registry_path(tmp_path):
    return tmp_path / ".state" / "network_sync_manifest.json"


# --------------------------------------------------------------------------- #
# The registry itself
# --------------------------------------------------------------------------- #
class TestRegistryPersistence:
    def test_round_trips_through_a_fresh_load(self, registry_path):
        store = reg.IngestionRegistry.load(registry_path)
        store.record(r"\\host\share\UT\A.docx", 1234, 1700000000.0, sha256="ab" * 32)
        store.save()

        # A brand-new process would see exactly this.
        reloaded = reg.IngestionRegistry.load(registry_path)
        record = reloaded.get(r"\\host\share\UT\A.docx")
        assert record is not None
        assert (record.size, record.mtime) == (1234, 1700000000.0)
        assert record.sha256 == "ab" * 32
        assert record.staged_at            # stamped, not blank

    def test_lookup_is_case_insensitive_like_windows_paths(self, registry_path):
        store = reg.IngestionRegistry.load(registry_path)
        store.record(r"\\HOST\Share\UT\A.docx", 10, 1.0)
        assert store.get(r"\\host\share\ut\a.docx") is not None

    def test_save_leaves_no_temp_debris(self, registry_path):
        store = reg.IngestionRegistry.load(registry_path)
        store.record(r"\\host\share\UT\A.docx", 10, 1.0)
        store.save()
        assert list(registry_path.parent.iterdir()) == [registry_path]

    @pytest.mark.parametrize("payload", [
        "{ not json",                                  # corrupt
        '{"version": 99, "files": {"x": {}}}',         # written by a newer build
        '["not", "a", "dict"]',                        # wrong shape
    ])
    def test_unusable_manifest_loads_empty_and_never_raises(self, registry_path, payload):
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(payload, encoding="utf-8")
        store = reg.IngestionRegistry.load(registry_path)
        assert len(store) == 0

    def test_missing_manifest_loads_empty(self, registry_path):
        assert len(reg.IngestionRegistry.load(registry_path)) == 0

    def test_a_malformed_record_is_dropped_not_fatal(self, registry_path):
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps({
            "version": reg.SCHEMA_VERSION,
            "files": {"good": {"unc_path": "good", "size": 5, "mtime": 1.0},
                      "bad": {"unc_path": "bad", "size": "not-a-number"}},
        }), encoding="utf-8")
        store = reg.IngestionRegistry.load(registry_path)
        assert store.get("good") is not None
        assert store.get("bad") is None

    def test_schema_1_manifest_survives_the_upgrade(self, registry_path):
        """The cutoff engine's map must not be lost when the file gains `files`."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps({
            "version": 1,
            "cutoff": "2025-12-01",
            "entries": {"deadbeef": {"name": "A.docx", "date": None,
                                     "staged_at": "2026-01-01T00:00:00"}},
        }), encoding="utf-8")

        store = reg.IngestionRegistry.load(registry_path)
        assert store.entries["deadbeef"]["name"] == "A.docx"
        assert len(store) == 0                     # no fingerprints yet
        store.record(r"\\host\share\UT\A.docx", 10, 1.0)
        store.save()

        data = json.loads(registry_path.read_text(encoding="utf-8"))
        assert data["version"] == reg.SCHEMA_VERSION
        assert data["cutoff"] == "2025-12-01"      # round-tripped, not clobbered
        assert "deadbeef" in data["entries"]
        assert len(data["files"]) == 1


class TestIsUnchanged:
    def test_exact_match_is_unchanged(self, registry_path):
        store = reg.IngestionRegistry.load(registry_path)
        store.record("p", 100, 1700000000.0)
        assert store.is_unchanged("p", 100, 1700000000.0)

    def test_unknown_path_is_never_unchanged(self, registry_path):
        assert not reg.IngestionRegistry.load(registry_path).is_unchanged("p", 1, 1.0)

    def test_a_changed_size_is_a_change(self, registry_path):
        store = reg.IngestionRegistry.load(registry_path)
        store.record("p", 100, 1700000000.0)
        assert not store.is_unchanged("p", 101, 1700000000.0)

    def test_a_moved_mtime_is_a_change(self, registry_path):
        store = reg.IngestionRegistry.load(registry_path)
        store.record("p", 100, 1700000000.0)
        assert not store.is_unchanged("p", 100, 1700000600.0)

    def test_sub_tolerance_drift_is_not_a_change(self, registry_path):
        """A copy across filesystems rounds the timestamp; that is not an edit."""
        store = reg.IngestionRegistry.load(registry_path)
        store.record("p", 100, 1700000000.0)
        drift = reg.MTIME_TOLERANCE_S / 2
        assert store.is_unchanged("p", 100, 1700000000.0 + drift)
        assert not store.is_unchanged("p", 100,
                                      1700000000.0 + reg.MTIME_TOLERANCE_S + 1)

    def test_a_known_hash_survives_a_hashless_re_record(self, registry_path):
        """Re-fingerprinting an untransferred file must not lose content evidence."""
        store = reg.IngestionRegistry.load(registry_path)
        store.record("p", 100, 1.0, sha256="cafe")
        store.record("p", 100, 2.0)
        assert store.get("p").sha256 == "cafe"


# --------------------------------------------------------------------------- #
# O(1) skipping over the (fake) share
# --------------------------------------------------------------------------- #
class TestFastMetadataSkip:
    def test_second_run_transfers_nothing(self, tmp_path, monkeypatch):
        share = tmp_path / "share" / "UT"
        for n in range(3):
            _write(share / "UT-2026" / "C" / f"U-UT-26-10{n}.docx", f"body{n}".encode())
        settings = _settings(tmp_path, [share])

        first = _sync(settings, tmp_path)
        assert first.staged_count == 3

        # The sharpest available proof of "no SMB transfer": copying at all is fatal.
        def _boom(*_a, **_k):
            raise AssertionError("an unchanged file must never be copied")

        monkeypatch.setattr(ni.shutil, "copy2", _boom)
        second = _sync(settings, tmp_path)

        assert second.checked == 3
        assert second.unchanged == 3
        assert second.staged == []
        assert second.modified == []

    def test_the_skip_does_not_even_index_the_input_tree(self, tmp_path, monkeypatch):
        """The O(1) claim: an all-unchanged run walks input/ zero times."""
        share = tmp_path / "share" / "UT"
        _write(share / "UT-2026" / "C" / "U-UT-26-110.docx")
        settings = _settings(tmp_path, [share])
        _sync(settings, tmp_path)

        def _boom(*_a, **_k):
            raise AssertionError("the local index must not be built on a warm run")

        monkeypatch.setattr(ni, "_local_index", _boom)
        assert _sync(settings, tmp_path).unchanged == 1

    def test_a_new_file_still_gets_staged_beside_known_ones(self, tmp_path):
        share = tmp_path / "share" / "UT"
        _write(share / "UT-2026" / "C" / "U-UT-26-120.docx", b"old")
        settings = _settings(tmp_path, [share])
        _sync(settings, tmp_path)

        _write(share / "UT-2026" / "C" / "U-UT-26-121.docx", b"new")
        result = _sync(settings, tmp_path)

        assert result.checked == 2
        assert result.unchanged == 1
        assert result.staged == ["U-UT-26-121.docx"]

    def test_registry_records_the_full_fingerprint(self, tmp_path, registry_path):
        share = tmp_path / "share" / "UT"
        src = _write(share / "UT-2026" / "C" / "U-UT-26-130.docx", b"payload")
        settings = _settings(tmp_path, [share])

        ni.sync_from_lan(settings, "2026-08", timeout=None,
                         registry_path=registry_path, log=lambda _m: None)

        record = reg.IngestionRegistry.load(registry_path).get(src)
        assert record is not None
        assert record.unc_path == str(src)
        assert record.size == src.stat().st_size
        assert record.mtime == pytest.approx(src.stat().st_mtime)
        assert record.sha256 is not None            # it was copied, so it was hashed
        assert record.staged_at

    def test_an_unwritable_registry_does_not_fail_the_run(self, tmp_path, monkeypatch):
        share = tmp_path / "share" / "UT"
        _write(share / "UT-2026" / "C" / "U-UT-26-140.docx")
        settings = _settings(tmp_path, [share])

        def _boom(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr(reg, "write_manifest", _boom)
        result = _sync(settings, tmp_path)

        assert result.staged_count == 1             # the file still landed


class TestModificationDetection:
    def test_an_edited_share_file_replaces_the_local_copy(self, tmp_path):
        share = tmp_path / "share" / "UT"
        src = _write(share / "UT-2026" / "C" / "U-UT-26-150.docx", b"version-one")
        settings = _settings(tmp_path, [share])
        _sync(settings, tmp_path)
        staged = next(Path(settings.input_dir).rglob("U-UT-26-150.docx"))
        assert staged.read_bytes() == b"version-one"

        # Edited on the share under the same name — the case the filename index
        # could never see.
        src.write_bytes(b"version-two-is-longer")
        os.utime(src, (time.time() + 60, time.time() + 60))
        result = _sync(settings, tmp_path)

        assert result.modified == ["U-UT-26-150.docx"]
        assert result.staged == []
        assert staged.read_bytes() == b"version-two-is-longer"   # overwritten in place
        assert _local_names(settings) == ["U-UT-26-150.docx"]    # no -lan twin

    def test_it_replaces_a_copy_that_was_sorted_into_a_method_folder(self, tmp_path):
        """STAGE 0 moves files out of UnSorted/; the replace must follow them."""
        share = tmp_path / "share" / "UT"
        src = _write(share / "UT-2026" / "C" / "U-UT-26-151.docx", b"one")
        settings = _settings(tmp_path, [share])
        _sync(settings, tmp_path)
        staged = next(Path(settings.input_dir).rglob("U-UT-26-151.docx"))
        sorted_to = settings.input_dir / "UT" / staged.name
        sorted_to.parent.mkdir(parents=True, exist_ok=True)
        staged.rename(sorted_to)

        src.write_bytes(b"two")
        os.utime(src, (time.time() + 60, time.time() + 60))
        _sync(settings, tmp_path)

        assert sorted_to.read_bytes() == b"two"
        assert _local_names(settings) == ["U-UT-26-151.docx"]

    def test_two_local_copies_fall_back_to_a_twin(self, tmp_path):
        """Ambiguous target: never guess which copy is authoritative."""
        share = tmp_path / "share" / "UT"
        src = _write(share / "UT-2026" / "C" / "U-UT-26-152.docx", b"one")
        settings = _settings(tmp_path, [share])
        _sync(settings, tmp_path)
        first = next(Path(settings.input_dir).rglob("U-UT-26-152.docx"))
        second = settings.input_dir / "UT" / first.name
        second.parent.mkdir(parents=True, exist_ok=True)
        second.write_bytes(b"one")

        src.write_bytes(b"two")
        os.utime(src, (time.time() + 60, time.time() + 60))
        result = _sync(settings, tmp_path)

        assert result.modified == ["U-UT-26-152-lan.docx"]
        assert first.read_bytes() == b"one"         # neither original destroyed
        assert second.read_bytes() == b"one"

    def test_a_timestamp_only_touch_is_not_a_modification(self, tmp_path):
        """Same bytes, new mtime: re-hashed once, then reported as unchanged."""
        share = tmp_path / "share" / "UT"
        src = _write(share / "UT-2026" / "C" / "U-UT-26-153.docx", b"stable")
        settings = _settings(tmp_path, [share])
        _sync(settings, tmp_path)

        os.utime(src, (time.time() + 120, time.time() + 120))
        result = _sync(settings, tmp_path)

        assert result.modified == []
        assert result.unchanged == 1
        assert _local_names(settings) == ["U-UT-26-153.docx"]
        # The refreshed fingerprint makes the NEXT run skip without re-hashing.
        assert _sync(settings, tmp_path).unchanged == 1

    def test_the_share_file_is_never_written(self, tmp_path):
        share = tmp_path / "share" / "UT"
        src = _write(share / "UT-2026" / "C" / "U-UT-26-154.docx", b"one")
        settings = _settings(tmp_path, [share])
        _sync(settings, tmp_path)

        src.write_bytes(b"two")
        os.utime(src, (time.time() + 60, time.time() + 60))
        before = (src.read_bytes(), src.stat().st_mtime)
        _sync(settings, tmp_path)

        assert src.read_bytes() == before[0]
        assert src.stat().st_mtime == pytest.approx(before[1])

    def test_a_refreshed_pdf_never_overwrites_the_docx(self, tmp_path):
        """Regression: a share .pdf refresh once replaced its stem twin .docx with
        PDF bytes (KF-MT-26-066 / KF-UT-26-022 went "unreadable")."""
        share = tmp_path / "share" / "UT"
        folder = share / "UT-2026" / "C"
        _write(folder / "U-UT-26-155.docx", b"PK-docx-original")
        settings = _settings(tmp_path, [share])
        _sync(settings, tmp_path)
        docx = next(Path(settings.input_dir).rglob("U-UT-26-155.docx"))

        # The PDF appears later: recorded by stem ("Up to date"), not copied.
        pdf = _write(folder / "U-UT-26-155.pdf", b"%PDF-first")
        _sync(settings, tmp_path)
        # Then it is edited on the share — the MODIFIED branch.
        pdf.write_bytes(b"%PDF-second-and-longer")
        os.utime(pdf, (time.time() + 60, time.time() + 60))
        _sync(settings, tmp_path)

        assert docx.read_bytes() == b"PK-docx-original"
        local_pdfs = [p for p in Path(settings.input_dir).rglob("*.pdf")]
        assert [p.read_bytes() for p in local_pdfs] == [b"%PDF-second-and-longer"]

    def test_stem_twins_each_refresh_their_own_suffix(self, tmp_path):
        """A live .docx and .pdf of one stem: each refresh lands on its own kind,
        in place, with no -lan twin."""
        share = tmp_path / "share" / "UT"
        folder = share / "UT-2026" / "C"
        src_docx = _write(folder / "U-UT-26-156.docx", b"PK-one")
        src_pdf = _write(folder / "U-UT-26-156.pdf", b"%PDF-one")
        settings = _settings(tmp_path, [share])
        _sync(settings, tmp_path)
        # Both kinds live locally (the stem skip staged only one of them).
        local = settings.input_dir / "UT"
        for src in (src_docx, src_pdf):
            if not list(Path(settings.input_dir).rglob(src.name)):
                _write(local / src.name, src.read_bytes())
        docx = next(Path(settings.input_dir).rglob("U-UT-26-156.docx"))
        pdf = next(Path(settings.input_dir).rglob("U-UT-26-156.pdf"))

        later = time.time() + 60
        src_docx.write_bytes(b"PK-two-is-longer")
        src_pdf.write_bytes(b"%PDF-two-is-longer")
        for src in (src_docx, src_pdf):
            os.utime(src, (later, later))
        result = _sync(settings, tmp_path)

        assert sorted(result.modified) == ["U-UT-26-156.docx", "U-UT-26-156.pdf"]
        assert docx.read_bytes() == b"PK-two-is-longer"
        assert pdf.read_bytes() == b"%PDF-two-is-longer"
        assert _local_names(settings) == ["U-UT-26-156.docx", "U-UT-26-156.pdf"]


# --------------------------------------------------------------------------- #
# Incremental compilation (main.py)
# --------------------------------------------------------------------------- #
def _compiled(tmp_path, name="compiled_monthly_report_UBOC_JUN_2026.pdf"):
    """An already-compiled PDF + sidecar pair on disk.

    ADR-004 tree: ``output/<CLIENT>/`` — the method folder is gone, because a
    compiled document is one month of one client across every method.
    """
    out = tmp_path / "output" / "UBOC" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"%PDF-1.4")
    out.with_suffix(".json").write_text("{}", encoding="utf-8")
    return out


class TestGroupIsCurrent:
    def test_untouched_group_with_both_artifacts_is_reused(self, tmp_path):
        out = _compiled(tmp_path)
        assert main._group_is_current(out, "UBOC", dirty=set(),
                                      config_stamp=0.0, incremental=True)

    def test_a_dirty_client_forces_a_render(self, tmp_path):
        out = _compiled(tmp_path)
        assert not main._group_is_current(out, "UBOC", dirty={"UBOC"},
                                          config_stamp=0.0, incremental=True)

    def test_another_clients_change_does_not_force_a_render(self, tmp_path):
        out = _compiled(tmp_path)
        assert main._group_is_current(out, "UBOC", dirty={"AZF"},
                                      config_stamp=0.0, incremental=True)

    def test_a_missing_sidecar_forces_a_render(self, tmp_path):
        out = _compiled(tmp_path)
        out.with_suffix(".json").unlink()
        assert not main._group_is_current(out, "UBOC", dirty=set(),
                                          config_stamp=0.0, incremental=True)

    def test_a_missing_pdf_forces_a_render(self, tmp_path):
        out = _compiled(tmp_path)
        out.unlink()
        assert not main._group_is_current(out, "UBOC", dirty=set(),
                                          config_stamp=0.0, incremental=True)

    def test_a_newer_config_forces_a_render(self, tmp_path):
        """An edited settings.yaml / dictionary invalidates every compiled PDF."""
        out = _compiled(tmp_path)
        assert not main._group_is_current(out, "UBOC", dirty=set(),
                                          config_stamp=out.stat().st_mtime + 60,
                                          incremental=True)

    def test_the_feature_switch_disables_everything(self, tmp_path):
        out = _compiled(tmp_path)
        assert not main._group_is_current(out, "UBOC", dirty=set(),
                                          config_stamp=0.0, incremental=False)


class TestForceRebuildFlag:
    def test_default_is_incremental(self):
        assert main.build_parser().parse_args([]).force_rebuild is False

    def test_flag_disables_the_skip(self):
        assert main.build_parser().parse_args(["--force-rebuild"]).force_rebuild is True


class TestDirtyClients:
    """``_dirty_clients`` — the incremental blast radius, keyed by CLIENT.

    It was ``(method, client)`` until ADR-004. With one document per client-month
    the method half named nothing a group could be looked up by, so it went; the
    client alone gives the identical guarantee, and a method-only change now
    correctly dirties the whole client (its rows share one document).
    """

    def test_a_changed_file_marks_its_own_group(self):
        members = {("2026-06", "UBOC"): [Path("in/U-UT-26-001.docx")]}
        assert main._dirty_clients(members, {"u-ut-26-001.docx"}) == {"UBOC"}

    def test_the_mark_spreads_across_months_for_the_same_client(self):
        """A June retest can pull its May parent, so May's PDF is stale too."""
        members = {
            ("2026-05", "UBOC"): [Path("in/U-UT-26-001.docx")],
            ("2026-06", "UBOC"): [Path("in/U-UT-26-050.docx")],
        }
        assert main._dirty_clients(members, {"u-ut-26-050.docx"}) == {"UBOC"}

    def test_it_does_not_spread_to_other_clients(self):
        members = {
            ("2026-06", "UBOC"): [Path("in/U-UT-26-001.docx")],
            ("2026-06", "AZF"): [Path("in/A-UT-26-002.docx")],
        }
        assert main._dirty_clients(members, {"u-ut-26-001.docx"}) == {"UBOC"}

    def test_a_changed_file_of_one_method_dirties_the_whole_client(self):
        """One document carries every method, so there is no finer unit to dirty."""
        members = {("2026-06", "UBOC"): [Path("in/U-UT-26-001.docx"),
                                         Path("in/U-MT-26-003.docx")]}
        assert main._dirty_clients(members, {"u-mt-26-003.docx"}) == {"UBOC"}

    def test_nothing_changed_means_nothing_dirty(self):
        members = {("2026-06", "UBOC"): [Path("in/U-UT-26-001.docx")]}
        assert main._dirty_clients(members, set()) == set()


class TestConfigStamp:
    def test_it_tracks_the_newest_of_its_inputs(self, tmp_path, monkeypatch):
        translations = tmp_path / "translations.yaml"
        translations.write_text("{}", encoding="utf-8")
        os.utime(translations, (1_800_000_000, 1_800_000_000))
        settings = SimpleNamespace(translations_path=translations)

        assert main._config_stamp(settings) >= 1_800_000_000

    def test_a_missing_file_contributes_nothing(self, tmp_path, monkeypatch):
        """No dictionary on disk must not block every skip forever."""
        monkeypatch.setattr(main, "_ROOT", tmp_path)     # no config/settings.yaml here
        settings = SimpleNamespace(translations_path=tmp_path / "nope.yaml")
        assert main._config_stamp(settings) == 0.0


class TestGroupMembership:
    def test_discover_groups_publishes_its_members(self):
        """The side-channel main.py maps 'these files changed' onto 'these groups'."""
        from monthly_report import pre_processor as pp
        assert isinstance(pp.discover_groups.last_members, dict)
