"""The only writer in the application, and the file it is not allowed to damage.

``config/settings.yaml`` is ~310 lines of which a large share are comments that
explain why each value is what it is — why the takeover budget is 900 seconds,
why the director's name is three keys. It is also git-ignored, so a bad write has
no ``git checkout`` behind it.

So most of what is tested here is what the writer leaves ALONE. A round-trip
through ``yaml.safe_dump`` would pass a "the values are correct" test and still
be a data-loss bug; these tests are the ones that would catch it.
"""

from __future__ import annotations

import pytest

from monthly_report.gui.services import settings_writer as writer
from monthly_report.gui.services.settings_writer import (DIRECTOR_KEYS,
                                                         SettingsWriteError)

# The real block, comments and all, reproduced closely enough to be the thing
# under test rather than a simplified stand-in.
SETTINGS = """\
# ---------------------------------------------------------------------------
# E-Keyfiyyet portal integration (uploader.py).
# ---------------------------------------------------------------------------
portal:
  # The appeal form. This is the URL uploader.py WAITS FOR, not one it opens.
  url: "https://e-keyfiyyet.gov.az/uqq/new-appeal"

  takeover_timeout_seconds: 900

  # Value selected in the "Yeni sənəd *" dropdown.
  document_type: "İnspeksiya orqanının rəyi"

  # Signing director. REQUIRED before any --live run.
  #
  # The name is THREE keys, not one, because the portal has three separate
  # boxes. Fill these in exactly as they appear on the identity document.
  director:
    ad: "TEST"                       # (ad/name) — given name
    soyadi: "TESTƏROV"                # (soyadı/surname)
    atasinin_adi: "ATA"              # (atasının adı/middle name) — patronymic
    fin: "0FAKE01"                    # FİN
    seriya_nomresi: "09999901"        # Seriya nömrəsi

# Locale / language of the generated report.
locale:
  language: az
"""


@pytest.fixture
def settings(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(SETTINGS, encoding="utf-8")
    return path


def lines_of(path):
    return path.read_text(encoding="utf-8").splitlines()


class TestRead:
    def test_reads_the_director_through_the_parser(self, settings):
        assert writer.read_director(settings) == {
            "ad": "TEST", "soyadi": "TESTƏROV", "atasinin_adi": "ATA",
            "fin": "0FAKE01", "seriya_nomresi": "09999901"}

    def test_every_key_is_present_even_when_the_file_lacks_it(self, tmp_path):
        path = tmp_path / "s.yaml"
        path.write_text("portal:\n  director:\n    fin: \"X\"\n", encoding="utf-8")
        assert writer.read_director(path) == {
            "ad": "", "soyadi": "", "atasinin_adi": "", "fin": "X",
            "seriya_nomresi": ""}

    def test_a_blank_key_reads_as_empty_not_as_None(self, tmp_path):
        """`fin:` with nothing after it is YAML None, and must not reach a field."""
        path = tmp_path / "s.yaml"
        path.write_text("portal:\n  director:\n    fin:\n", encoding="utf-8")
        assert writer.read_director(path)["fin"] == ""

    def test_an_unquoted_serial_does_not_arrive_as_an_int(self, tmp_path):
        """09999901 unquoted would otherwise reach the form shorn of its zero."""
        path = tmp_path / "s.yaml"
        path.write_text("portal:\n  director:\n    seriya_nomresi: 9999901\n",
                        encoding="utf-8")
        assert writer.read_director(path)["seriya_nomresi"] == "9999901"

    def test_a_missing_file_is_an_error_with_a_readable_message(self, tmp_path):
        with pytest.raises(SettingsWriteError):
            writer.read_director(tmp_path / "absent.yaml")


class TestWriteLeavesTheFileAlone:
    def test_only_the_edited_lines_change(self, settings):
        before = lines_of(settings)
        writer.write_director(settings, {"fin": "7ABCD12"})
        after = lines_of(settings)

        changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        assert len(before) == len(after)
        assert len(changed) == 1
        assert after[changed[0]].strip().startswith("fin:")

    def test_the_comments_survive(self, settings):
        """The thing yaml.safe_dump would destroy, stated as a test."""
        writer.write_director(settings, dict.fromkeys(DIRECTOR_KEYS, "X"))
        text = settings.read_text(encoding="utf-8")

        assert "# E-Keyfiyyet portal integration (uploader.py)." in text
        assert "# The name is THREE keys, not one" in text
        assert "# Signing director. REQUIRED before any --live run." in text

    def test_the_per_key_inline_comments_survive(self, settings):
        writer.write_director(settings, {"ad": "ƏLİ", "fin": "7ABCD12"})
        text = settings.read_text(encoding="utf-8")

        assert 'ad: "ƏLİ"' in text
        assert "# (ad/name) — given name" in text
        assert "# FİN" in text

    def test_the_rest_of_the_portal_block_is_untouched(self, settings):
        writer.write_director(settings, {"fin": "7ABCD12"})
        text = settings.read_text(encoding="utf-8")

        assert "takeover_timeout_seconds: 900" in text
        assert 'document_type: "İnspeksiya orqanının rəyi"' in text
        assert 'url: "https://e-keyfiyyet.gov.az/uqq/new-appeal"' in text
        assert "language: az" in text

    def test_key_order_is_preserved(self, settings):
        """safe_dump would sort these alphabetically; the form's order is the portal's."""
        writer.write_director(settings, dict.fromkeys(DIRECTOR_KEYS, "X"))
        text = settings.read_text(encoding="utf-8")
        positions = [text.index(f"{key}:") for key in DIRECTOR_KEYS]
        assert positions == sorted(positions)

    def test_azerbaijani_values_are_not_escaped(self, settings):
        """allow_unicode=False would write TEST\\u018fROV and call it saved."""
        writer.write_director(settings, {"soyadi": "TESTƏROV", "ad": "ƏLİYEV"})
        text = settings.read_text(encoding="utf-8")

        assert "TESTƏROV" in text and "ƏLİYEV" in text
        assert "\\u" not in text

    def test_crlf_line_endings_are_not_normalised(self, tmp_path):
        """A save must not turn the whole file into a line-ending diff."""
        path = tmp_path / "crlf.yaml"
        path.write_bytes(SETTINGS.replace("\n", "\r\n").encode("utf-8"))

        writer.write_director(path, {"fin": "7ABCD12"})
        raw = path.read_bytes()

        assert b"\r\n" in raw
        assert raw.replace(b"\r\n", b"") .count(b"\n") == 0


class TestWriteRoundTrip:
    def test_values_read_back_as_written(self, settings):
        values = {"ad": "ƏLİ", "soyadi": "HÜSEYNOV", "atasinin_adi": "OQTAY",
                  "fin": "7ABCD12", "seriya_nomresi": "99001122"}
        writer.write_director(settings, values)
        assert writer.read_director(settings) == values

    def test_a_partial_edit_leaves_the_other_keys_as_they_were(self, settings):
        writer.write_director(settings, {"fin": "7ABCD12"})
        director = writer.read_director(settings)

        assert director["fin"] == "7ABCD12"
        assert director["ad"] == "TEST"
        assert director["seriya_nomresi"] == "09999901"

    def test_a_leading_zero_survives_because_the_value_is_quoted(self, settings):
        writer.write_director(settings, {"seriya_nomresi": "00012345"})
        assert writer.read_director(settings)["seriya_nomresi"] == "00012345"

    def test_a_value_containing_a_quote_is_escaped_and_reads_back_intact(self, settings):
        writer.write_director(settings, {"ad": 'O"BRIEN'})
        assert writer.read_director(settings)["ad"] == 'O"BRIEN'

    def test_a_value_containing_a_hash_is_not_read_back_as_a_comment(self, settings):
        writer.write_director(settings, {"ad": "A # B"})
        assert writer.read_director(settings)["ad"] == "A # B"

    def test_values_are_stripped(self, settings):
        writer.write_director(settings, {"fin": "  7ABCD12  "})
        assert writer.read_director(settings)["fin"] == "7ABCD12"

    def test_clearing_a_value_is_allowed(self, settings):
        """Blanking FİN is how an operator hands the app to someone else."""
        writer.write_director(settings, {"fin": ""})
        assert writer.read_director(settings)["fin"] == ""

    def test_a_key_the_file_never_had_is_added_not_dropped(self, tmp_path):
        path = tmp_path / "s.yaml"
        path.write_text("portal:\n  director:\n    fin: \"X\"\n", encoding="utf-8")

        writer.write_director(path, {"seriya_nomresi": "0099"})

        assert writer.read_director(path)["seriya_nomresi"] == "0099"
        assert writer.read_director(path)["fin"] == "X"


class TestBackupAndRefusal:
    def test_a_backup_is_left_behind(self, settings):
        writer.write_director(settings, {"fin": "7ABCD12"})
        backup = settings.with_suffix(settings.suffix + ".bak")

        assert backup.is_file()
        assert backup.read_text(encoding="utf-8") == SETTINGS

    def test_writing_the_same_values_does_not_touch_the_file(self, settings):
        """No churn, and no backup that overwrites the last real one."""
        current = writer.read_director(settings)
        writer.write_director(settings, current)

        assert settings.read_text(encoding="utf-8") == SETTINGS
        assert not settings.with_suffix(settings.suffix + ".bak").exists()

    def test_no_temp_files_are_left_in_the_config_directory(self, settings):
        writer.write_director(settings, {"fin": "7ABCD12"})
        assert not [p for p in settings.parent.iterdir() if p.suffix == ".tmp"]

    def test_a_line_break_in_a_value_is_refused(self, settings):
        with pytest.raises(SettingsWriteError, match="paste accident"):
            writer.write_director(settings, {"ad": "TEST\nTESTƏROV"})
        assert settings.read_text(encoding="utf-8") == SETTINGS

    def test_a_key_that_is_not_a_director_field_is_refused(self, settings):
        """The writer's whole safety story is that it edits five lines and no others."""
        with pytest.raises(SettingsWriteError, match="takeover_timeout_seconds"):
            writer.write_director(settings, {"takeover_timeout_seconds": "1"})
        assert settings.read_text(encoding="utf-8") == SETTINGS

    def test_a_file_with_no_portal_block_is_refused_rather_than_guessed_at(self, tmp_path):
        path = tmp_path / "s.yaml"
        path.write_text("locale:\n  language: az\n", encoding="utf-8")

        with pytest.raises(SettingsWriteError, match="portal"):
            writer.write_director(path, {"fin": "X"})
        assert path.read_text(encoding="utf-8") == "locale:\n  language: az\n"

    def test_a_portal_block_with_no_director_is_refused(self, tmp_path):
        path = tmp_path / "s.yaml"
        path.write_text("portal:\n  url: \"x\"\n", encoding="utf-8")

        with pytest.raises(SettingsWriteError, match="director"):
            writer.write_director(path, {"fin": "X"})

    def test_a_director_key_outside_portal_is_not_the_one_we_edit(self, tmp_path):
        """Located structurally: some other block's `director:` is a different director."""
        path = tmp_path / "s.yaml"
        path.write_text("archive:\n  director:\n    fin: \"OLD\"\n"
                        "portal:\n  director:\n    fin: \"REAL\"\n", encoding="utf-8")

        writer.write_director(path, {"fin": "NEW"})
        text = path.read_text(encoding="utf-8")

        assert 'fin: "OLD"' in text
        assert 'fin: "NEW"' in text
