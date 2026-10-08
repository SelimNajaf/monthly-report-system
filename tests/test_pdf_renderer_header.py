"""Header chrome of the compiled PDF: the serial caption, and what is NOT drawn.

Pure string / constant logic pulled out of the ReportLab canvas so it can be
pinned without rendering a page:

  * ``_serial_label`` — the top-right badge, captioned ``Hesabat №: <serial>`` with
    the label read from the translation dictionary (not hardcoded).
  * The per-method header subtitle — ``(RADİOQRAFİK ÜSUL / RT)`` and its siblings,
    once drawn as a third header line below the blue rule — is GONE. The method is
    carried per row in the Üsul column instead, so the banner would only repeat it.
    Its removal is pinned here because the band it occupied is also why the top
    margin could shrink.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report import pdf_renderer  # noqa: E402
from monthly_report.pdf_renderer import _serial_label  # noqa: E402


class _Translator:
    """Only the one term the badge caption needs."""
    def term(self, text):
        return "Hesabat №" if text == "Report Number Label" else text


def test_serial_badge_is_captioned_with_hesabat_no():
    assert (_serial_label(_Translator(), "MR-MPI-SDLN-26-05")
            == "Hesabat №: MR-MPI-SDLN-26-05")


def test_the_method_subtitle_band_is_gone():
    """No method banner anywhere in the renderer: not the map, not the wrapper it
    needed, not the paragraph style it drew with."""
    assert not hasattr(pdf_renderer, "_METHOD_SUBTITLE")
    assert not hasattr(pdf_renderer, "_wrap_words")


def test_no_method_banner_is_reachable_as_a_module_constant():
    """A leftover subtitle constant under any name would still be renderable, so
    scan the module's own string values rather than trusting the two names above.
    Comments and docstrings are exempt by construction — they cannot be drawn."""
    for name, value in vars(pdf_renderer).items():
        if name.startswith("__"):
            continue
        blobs = ([value] if isinstance(value, str)
                 else list(value.values()) if isinstance(value, dict) else [])
        for blob in blobs:
            assert "ÜSUL" not in str(blob).upper(), f"{name} still holds a method banner"


def test_top_margin_reclaims_the_subtitle_band():
    """The 42 mm top margin existed to hold logo + title + rule AND the subtitle
    below the rule. With the subtitle gone the rule (h - 25 mm) plus clearance is
    all that is needed, and the reclaimed space goes to table rows."""
    assert pdf_renderer._TOP == 30 * pdf_renderer.mm
