"""Contract tests binding uploader.py's locators to output/portal_form_probe.json.

Every locator in upload_report that survived the mapping pass is here because a
control in that dump carries the attribute it targets. These tests assert the
attribute is still there.

The reason this file exists rather than trusting the reading: the dump is the ONLY
evidence about a page none of us can open without an e-İmza card. If the portal
drops a placeholder in a release, the failure without these tests is a live run that
resolves nothing — or worse, resolves the wrong input and types a VÖEN into a
government form's verdict field. With them it is a red test naming the attribute
that moved.

Read-only over a committed artifact. No browser, no network.
"""

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from uploader import PORTAL_STANDARDS, _standard_key  # noqa: E402

_PROBE = _ROOT / "output" / "portal_form_probe.json"

pytestmark = pytest.mark.skipif(
    not _PROBE.is_file(),
    reason="no probe dump committed — run `python uploader.py --probe`")


@pytest.fixture(scope="module")
def dump():
    return json.loads(_PROBE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def controls(dump):
    return dump["controls"]


def _with_placeholder(controls, placeholder):
    return [c for c in controls if c.get("placeholder") == placeholder]


# --------------------------------------------------------------------------- #
# The attributes upload_report's mapped locators depend on.
# --------------------------------------------------------------------------- #
def test_probe_captured_the_expanded_form_not_the_collapsed_page(controls):
    """A 6-control dump is the pre-expansion page and maps nothing worth mapping."""
    assert len(controls) > 20, (
        "probe dump looks collapsed — --probe must pick the document type before "
        "dumping, or the form's fields are not in the DOM yet")


def test_document_type_combobox_is_labelled(controls):
    combos = [c for c in controls
              if c.get("role") == "combobox" and "Yeni sənəd" in c.get("label", "")]
    assert len(combos) == 1
    assert combos[0]["tag"] == "input", "an <input> combobox is a MUI Autocomplete"


def test_document_type_is_not_a_select(controls):
    """select_option() only works on <select>. The dump has none."""
    assert [c for c in controls if c["tag"] == "select"] == []


# --------------------------------------------------------------------------- #
# PORTAL_STANDARDS vs the portal. output/portal_form_probe.json was captured by
# `--probe` on 2026-08-12 and carries the 16 options of that date. On 2026-10-06 the
# portal replaced them with 21 (operator screenshot, NOT yet probe-verified), so the
# reconciliation below is xfail until a new dump exists (TODO P0). Both tests stay
# written to skip on a dump older than schema 4.
# --------------------------------------------------------------------------- #
def test_the_dump_records_the_multiselect_options(dump):
    """Schema 4 added standard_options — the option list is not in `controls`.

    It cannot be: the options live in a React portal that mounts only while the
    listbox is open, so the querySelectorAll sweep never sees them. That is exactly
    why PORTAL_STANDARDS started life as a transcription instead of a measurement.
    """
    if dump.get("probe_schema", 0) < 4:
        pytest.skip("probe dump predates schema 4 — re-run `python uploader.py --probe` "
                    "to capture the standards list")
    assert dump["standard_options"], (
        "the probe reached the form but read no options from the 'inspeksiya:' "
        "multiselect — PORTAL_STANDARDS stays unverified")


#: The dump that holds the OLD list. PORTAL_STANDARDS moved to the operator's provisional
#: 21 on 2026-10-06 without a probe, so against this dump the test below must fail.
_PRE_2026_10_06_DUMP = "2026-08-12T10:10:17"


def test_registered_standards_match_the_portal_exactly(dump, request):
    """The one test that can prove PORTAL_STANDARDS is real rather than remembered.

    xfail ONLY while output/portal_form_probe.json is still the 2026-08-12 dump. Any new
    probe dump turns the marker off, so the test then passes or fails for real; and
    strict=True makes an unexpected pass on the old dump fail too.
    """
    if dump.get("probed_at") == _PRE_2026_10_06_DUMP:
        request.applymarker(pytest.mark.xfail(reason="probe pending (TODO P0)",
                                              strict=True))
    if dump.get("probe_schema", 0) < 4 or not dump.get("standard_options"):
        pytest.skip("no measured option list in the dump — re-run --probe")

    live = {_standard_key(o) for o in dump["standard_options"]}
    code = {_standard_key(o) for o in PORTAL_STANDARDS}
    only_code = sorted(o for o in PORTAL_STANDARDS if _standard_key(o) not in live)
    only_live = sorted(o for o in dump["standard_options"]
                       if _standard_key(o) not in code)
    assert (only_code, only_live) == ([], []), (
        f"PORTAL_STANDARDS has drifted from the portal. Only in code: {only_code}. "
        f"Only on the portal: {only_live}. Update the constant from the dump.")


@pytest.mark.parametrize("placeholder", ["VÖEN", "FİN", "Seriya nömrəsi"])
def test_placeholder_mapped_fields_still_exist(controls, placeholder):
    """These three have NO label — the placeholder is the whole identity."""
    matches = _with_placeholder(controls, placeholder)
    assert len(matches) == 1, f"expected exactly one input with placeholder {placeholder!r}"
    assert matches[0]["label"] == "", (
        f"{placeholder} grew a real <label> — get_by_label is now viable and the "
        f"placeholder locator should be revisited")


def test_exactly_two_date_fields_carry_the_dd_mm_yyyy_placeholder(controls):
    """nth(0)/nth(1) is only honest while there are exactly two."""
    assert len(_with_placeholder(controls, "DD.MM.YYYY")) == 2


def test_second_date_field_ships_prefilled(controls):
    """Why _fill_date verifies instead of trusting fill(): a no-op leaves today's date."""
    prefilled = [c for c in controls
                 if "selected date is" in c.get("aria_label", "")]
    assert prefilled, ("no prefilled date picker found — if the portal stopped "
                       "prefilling, _fill_date's clear step is now harmless but its "
                       "to_have_value assertion still earns its keep")


def test_legal_entity_radio_has_a_real_label(controls):
    radios = [c for c in controls
              if c.get("type") == "radio" and c.get("label") == "Hüquqi şəxs"]
    assert len(radios) == 1


def test_exactly_one_file_input(controls):
    """input[type=file] has no id, name or label — the type is the identity."""
    files = [c for c in controls if c.get("type") == "file"]
    assert len(files) == 1, "a second uploader makes the attach target a coin flip"


def test_save_button_is_findable_by_its_text(controls):
    assert [c for c in controls if c.get("text") == "Yadda saxla"]


# --------------------------------------------------------------------------- #
# The caption anchors — the only handle the un-labelled fields have.
# --------------------------------------------------------------------------- #
def _with_caption(controls, caption):
    return [c for c in controls if c.get("caption") == caption]


@pytest.mark.parametrize("caption", [
    "İnspeksiyanın olunan obyekt:",
    "inspeksiya:",
    "İstifadə olunmuş avadanlıqlar barədə qeyd:",
    "Nəticə:",
])
def test_anchored_caption_identifies_exactly_one_control(controls, caption):
    """_caption_anchor raises unless the caption is unique. Pin that here too, so a
    portal re-word is a red test rather than a failed run in front of the operator."""
    assert len(_with_caption(controls, caption)) == 1


def test_the_equipment_note_is_a_plain_text_input_we_can_type_into(controls):
    """:r2c: is the equipment note. It is the field the sidecar's equipment_used fills.

    Its wrapper carries step="0.01" min="0" — numeric leftovers in the portal's own
    markup. type is "text", so a string fill is right; if that ever flips to
    type="number" our joined "EPOCH LT (№ 050010402), ..." would be silently rejected
    by the browser, so pin the type.
    """
    field = _with_caption(controls, "İstifadə olunmuş avadanlıqlar barədə qeyd:")
    assert len(field) == 1
    assert field[0]["tag"] == "input"
    assert field[0]["type"] == "text"


def test_the_field_we_deliberately_skip_is_still_between_the_ones_we_fill(controls):
    """:r2d: is what ordinal guessing would have hit instead of Nəticə.

    :r2c: used to be skipped alongside it and is now filled from equipment_used;
    :r2d: (free-text "additional information") has no source in the sidecar and
    stays untouched.
    """
    captions = [c.get("caption") for c in controls]
    assert "Əlavə məlumat:" in captions


def test_the_director_name_is_three_boxes(controls):
    """One configured full_name cannot fill three boxes without guessing word order."""
    group = [c for c in controls if "(ad/name)" in c.get("caption", "")]
    assert group, "the director group's caption markers are gone — re-map"
    caption = group[0]["caption"]
    for marker in ("(ad/name)", "(soyadı/surname)", "(atasının adı/middle name)"):
        assert marker in caption


def test_caption_walk_reads_the_previous_field_not_this_one(controls):
    """The probe's captionFor walks BACKWARD, so it is a hint and not proof.

    The proof is right here: this radio is labelled "Fiziki şəxs" but captioned
    "Hüquqi şəxs" — the previous radio's label. Anything relying on caption ==
    this field's caption is relying on the field being first in its group.

    If this test ever goes red because captions got fixed, that is good news — and
    it must be read before the anchors are trusted more widely, not after.
    """
    radios = [c for c in controls
              if c.get("type") == "radio" and c.get("label") == "Fiziki şəxs"]
    assert len(radios) == 1
    assert radios[0]["caption"] == "Hüquqi şəxs"


def test_the_client_name_fields_are_still_unidentifiable(controls):
    """Why upload_report writes neither. If they ever grow a caption, revisit."""
    anonymous = [c for c in controls
                 if c.get("id") in (":r26:", ":r27:")]
    for c in anonymous:
        assert not c.get("caption") and not c.get("label") and not c.get("placeholder")


# --------------------------------------------------------------------------- #
# The signature must stay a human decision.
# --------------------------------------------------------------------------- #
def test_e_imza_button_exists_on_the_page(controls):
    """It is on the form. The safeguard is that no locator in uploader.py finds it."""
    assert [c for c in controls if "E-imza" in c.get("text", "")]


def test_no_code_locates_the_e_imza_button():
    """A signature clicked by automation is a signature the operator did not give."""
    source = (_ROOT / "uploader.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        if "E-imza" not in line and "E-İmza" not in line:
            continue
        assert not any(call in line for call in
                       ("get_by_role", "get_by_text", "get_by_label", "locator(")), (
            f"uploader.py appears to locate the e-imza button: {line.strip()}")
