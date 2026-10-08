"""Dictionary-authoritative English -> Azerbaijani translation.

The JSON dictionary (``translations/az.json``) always wins, guaranteeing
consistent official terminology. Values with no dictionary entry are kept as-is;
when a value is *expected* to be a controlled term (e.g. an interpretation
phrase) but is missing from the dictionary, it is flagged with the configured
marker so gaps are auditable rather than silently dropped. The disabled
machine-translation hook is left for later.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_dictionary(path: str | Path) -> dict[str, str]:
    """Load az.json (ignoring ``_meta``) into a case-insensitive lookup table."""
    with Path(path).open(encoding="utf-8") as fh:
        raw = json.load(fh)
    return {str(k).strip().lower(): str(v)
            for k, v in raw.items() if k != "_meta"}


class Translator:
    """Case-insensitive dictionary translator with untranslated-gap tracking."""

    def __init__(self, dictionary: dict[str, str], settings=None):
        self.dictionary = dictionary
        self.flag = getattr(settings, "flag_untranslated", True)
        self.marker = getattr(settings, "untranslated_marker", "[AZ?]")
        self.untranslated: set[str] = set()

    def lookup(self, text: str) -> str | None:
        """Exact case-insensitive dictionary hit, or None."""
        if not text:
            return None
        return self.dictionary.get(text.strip().lower())

    def term(self, text: str) -> str:
        """Translate if known; otherwise return the original unchanged (identifiers)."""
        return self.lookup(text) or text

    def controlled(self, text: str) -> str:
        """Translate an expected controlled phrase; flag it if absent from the dict."""
        if not text or not text.strip():
            return ""
        hit = self.lookup(text)
        if hit is not None:
            return hit
        self.untranslated.add(text.strip())
        return f"{self.marker} {text.strip()}" if self.flag else text.strip()
