"""Configuration loading and validation.

Loads ``config/settings.yaml``, resolves every relative path against the project
root, and exposes a single ``Settings`` object to the rest of the pipeline. Fails
fast with a clear error when a required key or referenced file (e.g. a font TTF)
is missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Settings:
    """Validated, path-resolved settings for one pipeline run."""

    project_root: Path
    target_month: str                     # "YYYY-MM"
    input_dir: Path
    output_dir: Path
    translations_path: Path
    fonts_dir: Path
    images_dir: Path
    font_regular: Path
    font_bold: Path
    header_logo: Path
    stamp_logo: Path
    report_title: str
    doc_number_pattern: str
    output_pattern: str
    date_format: str
    dayfirst: bool
    flag_untranslated: bool
    untranslated_marker: str
    raw: dict = field(default_factory=dict)


def _require(d: dict, *keys: str):
    """Fetch a nested key, raising a clear error if any level is absent."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            raise KeyError(f"settings.yaml: missing required key '{'.'.join(keys)}'")
        cur = cur[k]
    return cur


def load_settings(settings_path: str | Path) -> Settings:
    """Read settings.yaml and return a validated :class:`Settings`."""
    settings_path = Path(settings_path).resolve()
    if not settings_path.is_file():
        raise FileNotFoundError(f"Settings file not found: {settings_path}")

    # Project root = parent of the config/ directory holding settings.yaml.
    project_root = settings_path.parent.parent
    with settings_path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    def rooted(*parts: str) -> Path:
        return (project_root / Path(*parts)).resolve()

    paths = _require(raw, "paths")
    fonts_dir = rooted(paths["fonts_dir"])
    images_dir = rooted(paths.get("images_dir", "images"))
    branding = raw.get("branding", {})

    font_regular = fonts_dir / _require(raw, "fonts", "regular")
    font_bold = fonts_dir / _require(raw, "fonts", "bold")
    for f in (font_regular, font_bold):
        if not f.is_file():
            raise FileNotFoundError(
                f"Required font missing: {f}. Place the TTF in {fonts_dir} "
                "(see assets/fonts/README.md)."
            )

    header_logo = images_dir / branding.get("header_logo", "")
    stamp_logo = images_dir / branding.get("stamp_logo", "")

    return Settings(
        project_root=project_root,
        target_month=str(_require(raw, "target_month")),
        input_dir=rooted(paths["input_dir"]),
        output_dir=rooted(paths["output_dir"]),
        translations_path=rooted(paths["translations"]),
        fonts_dir=fonts_dir,
        images_dir=images_dir,
        font_regular=font_regular,
        font_bold=font_bold,
        header_logo=header_logo,
        stamp_logo=stamp_logo,
        report_title=branding.get("report_title", "AYLIQ YOXLAMA HESABATI"),
        doc_number_pattern=branding.get("doc_number_pattern", "MR-{method}-{client}-{yy}-{mm}"),
        output_pattern=_require(raw, "output", "filename_pattern"),
        date_format=raw.get("locale", {}).get("date_format", "%d.%m.%Y"),
        dayfirst=bool(raw.get("date_detection", {}).get("dayfirst", True)),
        flag_untranslated=bool(raw.get("translation", {}).get("flag_untranslated", True)),
        untranslated_marker=raw.get("translation", {}).get("untranslated_marker", "[AZ?]"),
        raw=raw,
    )
