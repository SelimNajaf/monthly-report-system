"""Load the pipeline's settings for the GUI, and pre-flight the things that bite.

``config.load_settings`` is deliberately fail-fast: it raises ``FileNotFoundError``
when a DejaVu TTF is missing (config.py:73-78) or ``KeyError`` when a required
key is absent. In a terminal that is a clear message. In a GUI it is a dialog
nobody reads, or worse, a crash on startup.

So the dashboard asks these questions *before* arming the Run button, and reports
them as a checklist the user can act on.

I/O contract
------------
load_settings() -> Settings      # raises SettingsError with a readable message
health() -> list[Check]
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import app_paths


class SettingsError(RuntimeError):
    """Settings could not be loaded — carries a message fit for a status banner."""


@dataclass(frozen=True)
class Check:
    """One pre-flight result."""

    label: str
    ok: bool
    detail: str


def load_settings():
    """Load ``config/settings.yaml`` from :func:`app_paths.app_root`.

    Imported lazily: the settings module pulls in PyYAML, and a GUI that cannot
    open at all is worse than one that opens and explains what is wrong.
    """
    from monthly_report import config

    path = app_paths.settings_path()
    try:
        return config.load_settings(path)
    except FileNotFoundError as exc:
        raise SettingsError(str(exc)) from exc
    except KeyError as exc:
        raise SettingsError(f"settings.yaml is incomplete: {exc}") from exc
    except Exception as exc:
        raise SettingsError(f"Could not read {path}: {exc}") from exc


def _check_dir(root: Path, name: str, purpose: str) -> Check:
    path = root / name
    return Check(f"{name}/", path.is_dir(), purpose if path.is_dir() else f"missing: {path}")


def health() -> list[Check]:
    """Every condition the pipeline needs, checked without running it.

    Ordered so the first failure is the most likely cause of the rest: no
    ``config/`` beside the executable means nothing else can resolve either.
    """
    root = app_paths.app_root()
    checks = [
        Check("Application root", root.is_dir(), str(root)),
        _check_dir(root, "config", "settings.yaml found"),
        _check_dir(root, "input", "source documents"),
        _check_dir(root, "assets", "fonts and branding"),
        _check_dir(root, "translations", "Azerbaijani dictionary"),
    ]

    try:
        settings = load_settings()
    except SettingsError as exc:
        checks.append(Check("Settings", False, str(exc)))
        return checks

    checks.append(Check("Settings", True, f"target month {settings.target_month}"))
    # Fonts are the classic silent killer: without them load_settings raises and
    # every run dies before touching a document.
    for label, font in (("Font (regular)", settings.font_regular),
                        ("Font (bold)", settings.font_bold)):
        checks.append(Check(label, font.is_file(), font.name if font.is_file()
                            else f"missing: {font}"))
    checks.append(Check("Output directory", True, str(settings.output_dir)))

    try:
        import playwright  # noqa: F401

        playwright_ok, detail = True, "installed (needed only for live uploads)"
    except ImportError:
        playwright_ok, detail = False, "not installed — dry-run uploads still work"
    checks.append(Check("Playwright", playwright_ok, detail))

    return checks


def portal_readiness(settings) -> list[Check]:
    """The three pre-upload gates, as a checklist: VÖENs, director, standards.

    Separate from :func:`health` (environment/paths/fonts): this answers "will a live
    portal upload go through", not "can the pipeline run at all". Each check reuses the
    same primitive the pipeline itself uses, so the dashboard and a real run agree:

    * **VÖENs** — every configured client resolves to a non-empty tax ID
      (``method_registry.client_voen``; an empty string is the pipeline's "missing").
    * **Director** — the portal's ``fin`` and ``seriya_nomresi`` are set, mirroring
      ``uploader.assert_director_configured`` (name parts the portal auto-fills are not
      required).
    * **Standards** — every ``input/`` filename's NDT standard is on the allowlist
      (``method_registry.is_allowed_standard``); an unmapped one is quarantined at run
      time, so flagging it here is the earlier, cheaper warning.

    Pure and read-only — safe to call on every scan to paint the header chip.
    """
    from monthly_report import docx_reader, method_registry
    from . import app_paths
    from .settings_writer import read_director

    checks: list[Check] = []

    # VÖENs — checked over the clients that can actually be FILED. A registered but
    # non-approved client carries a blank VÖEN on purpose (unverified tax ID: it
    # compiles, it never uploads), so flagging it would make this check permanently
    # red over a deliberate state. With the allowlist off, every client is fileable
    # and every client is checked, exactly as before.
    registry = (settings.raw.get("clients") if settings.raw else None) or {}
    checked_voen, missing_voen = [], []
    for key, spec in registry.items():
        spec = spec or {}
        code = str(spec.get("code", key))
        if not method_registry.is_approved_client(code, settings):
            continue
        checked_voen.append(code)
        if not method_registry.client_voen(code, settings).strip():
            missing_voen.append(code)
    if not registry:
        checks.append(Check("Client VÖENs", True, "no clients registered"))
    elif missing_voen:
        checks.append(Check("Client VÖENs", False,
                            f"missing for: {', '.join(missing_voen)}"))
    else:
        checks.append(Check("Client VÖENs", True,
                            f"all {len(checked_voen)} fileable client(s) configured"))

    # Director FIN / serial — the portal-identity gate.
    director = read_director(app_paths.settings_path())
    missing_dir = [k for k in ("fin", "seriya_nomresi") if not director.get(k, "").strip()]
    if missing_dir:
        checks.append(Check("Director FIN / serial", False,
                            f"missing: {', '.join(missing_dir)}"))
    else:
        checks.append(Check("Director FIN / serial", True, "FIN and serial set"))

    # NDT standards — every input filename's standard must be on the allowlist.
    input_dir = getattr(settings, "input_dir", None)
    unmapped = []
    if input_dir and input_dir.is_dir():
        for path in input_dir.iterdir():
            if not path.is_file() or path.name.startswith("~$"):
                continue
            std = docx_reader.parse_filename_metadata(path).get("standard")
            if std and not method_registry.is_allowed_standard(std, settings):
                unmapped.append(std)
    if unmapped:
        unique = sorted(set(unmapped))
        checks.append(Check("NDT standards", False,
                            f"{len(unmapped)} file(s) unmapped: {', '.join(unique)}"))
    else:
        checks.append(Check("NDT standards", True, "all on the allowed list"))

    return checks
