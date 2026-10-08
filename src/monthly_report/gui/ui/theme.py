"""Colours, fonts and the stylesheet — the whole look, in one file.

Every colour in the application is named here and nowhere else, for the same
reason ``pdf_renderer`` owns all PDF layout (ADR-001): a hex code sprinkled
through twenty widgets cannot be re-themed, and this app has to be re-themable
because it ships in dark and light.

I/O contract
------------
palette(dark: bool) -> Palette
stylesheet(palette) -> str
install_fonts() -> str      # family name to use for report text
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QFontDatabase

from ..services import app_paths


@dataclass(frozen=True)
class Palette:
    """Every colour the dashboard uses."""

    name: str
    window: str
    surface: str          # sidebar, panels
    card: str             # metric cards, group boxes
    card_hover: str
    border: str
    text: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_text: str
    success: str
    warning: str
    danger: str
    info: str
    console_bg: str
    console_text: str
    shadow: int           # drop-shadow alpha; light themes need a softer one

    def console_colour(self, name: str | None) -> str:
        """Map an ANSI colour name (services.ansi) onto the theme.

        The uploader's palette is fixed at 8 ANSI colours; the theme's is not.
        Routing through here means "SKIP is grey" stays legible on both a near
        black and a near white background.
        """
        return {
            "red": self.danger,
            "green": self.success,
            "yellow": self.warning,
            "blue": self.info,
            "magenta": self.accent,
            "cyan": self.info,
            "grey": self.text_muted,
            "white": self.console_text,
            "black": self.text_muted,
        }.get(name or "", self.console_text)


# Google Stitch "Executive Slate & Cobalt" — deep slate base, cobalt actions,
# emerald success, amber warnings. Tonal layering (window < surface < card_hover)
# stands in for the design's glassmorphism, which Qt QSS cannot render (no
# backdrop-blur, no box-shadow). See assets/stitch export DESIGN.md.
DARK = Palette(
    name="dark",
    window="#0F172A",           # slate-900 base
    surface="#1E293B",          # slate-800 panels/sidebar (glass, flattened)
    card="#1E293B",             # metric cards, group boxes
    card_hover="#26364A",       # elevated / hovered slate
    border="#334155",           # slate-700 — every panel & control stroke
    text="#D3E4FE",             # on-surface, cool near-white
    text_muted="#8C98AD",       # slate-grey secondary text/iconography
    accent="#3B82F6",           # electric cobalt — high-intent actions
    accent_hover="#2563EB",     # cobalt-600, pressed/hover
    accent_text="#FFFFFF",
    success="#10B981",          # emerald — pipeline success
    warning="#F59E0B",          # amber — warnings / process blocks
    danger="#EF4444",
    info="#38BDF8",
    console_bg="#020617",       # deep terminal slate
    console_text="#CBD5E1",
    shadow=170,
)

LIGHT = Palette(
    name="light",
    window="#F8FAFC",           # slate-50 base — the primary theme's canvas
    surface="#FFFFFF",
    card="#FFFFFF",
    card_hover="#EEF2F7",       # one step off window so hover/nav/drop states stay visible
    border="#CBD5E1",           # slate-300 — E2E8F0 was near-invisible on white inputs
    text="#0F172A",
    text_muted="#64748B",
    accent="#2563EB",
    accent_hover="#3B82F6",
    accent_text="#FFFFFF",
    success="#10B981",          # emerald — matches DARK for cross-theme consistency
    warning="#D97706",
    danger="#DC2626",
    info="#0284C7",
    console_bg="#0F172A",       # the console stays dark in both themes: it is a
    console_text="#CBD5E1",     # terminal, and executives expect one to look like one
    shadow=40,
)


#: The application's launch default. Light is now primary; the dark toggle stays intact.
#: Single source so the four spots that set an initial theme cannot drift apart.
DEFAULT_DARK = False


def palette(dark: bool = DEFAULT_DARK) -> Palette:
    return DARK if dark else LIGHT


def install_fonts() -> str:
    """Register the DejaVu fonts the pipeline already ships.

    Report names carry Azerbaijani glyphs (``ə ğ ı ö ş ç ü``). Rather than trust
    whatever Windows falls back to, the app loads the exact TTFs the PDF renderer
    embeds — so a filename looks the same in the console as it does in the report.
    Returns the family to use, or "" to accept the system default.
    """
    fonts_dir = app_paths.app_root() / "assets" / "fonts"
    family = ""
    for ttf in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
        path: Path = fonts_dir / ttf
        if not path.is_file():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id != -1 and not family:
            families = QFontDatabase.applicationFontFamilies(font_id)
            family = families[0] if families else ""
    return family


def stylesheet(p: Palette) -> str:
    """The full QSS.

    Written as one sheet rather than per-widget calls so the entire look can be
    swapped at runtime with a single ``setStyleSheet``.
    """
    return f"""
/* ----------------------------------------------------------------- base -- */
QWidget {{
    background: {p.window};
    color: {p.text};
    font-family: "Inter", "Segoe UI", "DejaVu Sans", sans-serif;
    font-size: 13px;
}}
QToolTip {{
    background: {p.card};
    color: {p.text};
    border: 1px solid {p.border};
    padding: 6px 8px;
    border-radius: 6px;
}}

/* -------------------------------------------------------------- sidebar -- */
#Sidebar {{
    background: {p.surface};
    border-right: 1px solid {p.border};
}}
#SidebarBrand {{
    color: {p.text};
    font-size: 16px;
    font-weight: 700;
    padding: 22px 20px 4px 20px;
    background: transparent;
}}
#SidebarTagline {{
    color: {p.text_muted};
    font-size: 11px;
    padding: 0 20px 18px 20px;
    background: transparent;
}}
#SidebarFooter {{
    color: {p.text_muted};
    font-size: 10px;
    padding: 12px 20px;
    background: transparent;
}}
QPushButton#NavButton {{
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    color: {p.text_muted};
    text-align: left;
    padding: 12px 18px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton#NavButton:hover {{
    background: {p.card_hover};
    color: {p.text};
}}
QPushButton#NavButton:checked {{
    background: {p.card};
    color: {p.accent};
    border-left: 3px solid {p.accent};
    font-weight: 600;
}}

/* ---------------------------------------------------------------- cards -- */
#Card, #Panel {{
    background: {p.card};
    border: 1px solid {p.border};
    border-radius: 8px;
}}
/* Semantic left-accent borders — the Stitch metric-card motif. Keyed off the card's
   dynamic `accent` property (MetricCard.__init__); the 4px longhand overrides only the
   left edge, so the other three sides keep the 1px panel stroke above. */
/* border-radius:0 on the accented card: a thick left border on a rounded rect makes Qt
   paint the corner arcs in the accent colour, bleeding a hairline onto the bottom/top
   edge. Square edges render the 4px strip cleanly; plain #Card/#Panel keep the 8px radius. */
#Card[accent="success"] {{ border-left: 4px solid {p.success}; border-radius: 0; }}
#Card[accent="warning"] {{ border-left: 4px solid {p.warning}; border-radius: 0; }}
#Card[accent="neutral"] {{ border-left: 4px solid {p.accent};  border-radius: 0; }}
#Card[accent="danger"]  {{ border-left: 4px solid {p.danger};  border-radius: 0; }}
#CardValue {{
    color: {p.text};
    font-size: 34px;
    font-weight: 700;
    background: transparent;
}}
/* The trend delta beside the number (↑ 12% / ↓ 4%). Colour is set inline by
   MetricCard.set_trend — green for a good move, amber for a bad one. */
#CardTrend {{
    font-size: 13px;
    font-weight: 700;
    background: transparent;
    padding-bottom: 5px;
}}
#CardTitle {{
    color: {p.text_muted};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    background: transparent;
}}
#CardCaption {{
    color: {p.text_muted};
    font-size: 11px;
    background: transparent;
}}
#CardIcon {{
    font-size: 22px;
    background: transparent;
}}
#PageTitle {{
    font-size: 22px;
    font-weight: 700;
    background: transparent;
}}
#PageSubtitle {{
    color: {p.text_muted};
    font-size: 12px;
    background: transparent;
}}
#SectionTitle {{
    color: {p.text_muted};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    background: transparent;
}}
#FieldLabel {{
    color: {p.text_muted};
    font-size: 11px;
    font-weight: 600;
    background: transparent;
}}
#Hint {{
    color: {p.text_muted};
    font-size: 11px;
    background: transparent;
}}

/* -------------------------------------------------------------- buttons -- */
QPushButton {{
    background: {p.card_hover};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 9px 16px;
    font-weight: 600;
}}
QPushButton:hover  {{ border-color: {p.accent}; }}
QPushButton:disabled {{ color: {p.text_muted}; border-color: {p.border}; }}

QPushButton#PrimaryButton {{
    background: {p.accent};
    color: {p.accent_text};
    border: none;
    border-radius: 6px;
    padding: 13px 20px;
    font-size: 14px;
    font-weight: 700;
}}
QPushButton#PrimaryButton:hover    {{ background: {p.accent_hover}; }}
QPushButton#PrimaryButton:disabled {{ background: {p.border}; color: {p.text_muted}; }}

QPushButton#DangerButton {{
    background: transparent;
    color: {p.danger};
    border: 1px solid {p.danger};
}}
QPushButton#DangerButton:hover    {{ background: {p.danger}; color: #FFFFFF; }}
QPushButton#DangerButton:disabled {{ color: {p.text_muted}; border-color: {p.border}; }}

/* Compact secondary action — the console's Clear/Copy and other in-header buttons.
   Smaller and quieter than a standard QPushButton so a title row does not shout. */
QPushButton#ToolButton {{
    background: transparent;
    color: {p.text_muted};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 5px 12px;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton#ToolButton:hover {{ color: {p.text}; border-color: {p.accent}; }}
QPushButton#ToolButton:disabled {{ color: {p.text_muted}; border-color: {p.border}; }}

/* Segmented control — the uploader's Run Mode strip. Checkable buttons sharing an
   exclusive group read as one pill: the checked segment is cobalt-on-tint, the rest
   flat and muted. Mirrors the Stitch active-segment (bg-primary/20 text-primary). */
QPushButton#Segment {{
    background: transparent;
    color: {p.text_muted};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 8px 16px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#Segment:hover {{ color: {p.text}; border-color: {p.accent}; }}
QPushButton#Segment:checked {{
    background: {p.accent};
    color: {p.accent_text};
    border-color: {p.accent};
}}
QPushButton#Segment:disabled {{ color: {p.text_muted}; border-color: {p.border}; }}

/* --------------------------------------------------------------- inputs -- */
QComboBox, QLineEdit {{
    background: {p.window};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 8px 12px;
    min-height: 18px;
    selection-background-color: {p.accent};
}}
QComboBox:hover, QLineEdit:hover {{ border-color: {p.accent}; }}
QLineEdit:focus {{ border-color: {p.accent}; }}
/* Compact filter/search field — sits above a table or list. Slightly tighter than a
   form input so it reads as a control over the view, not a field to fill. */
QLineEdit#SearchBox {{
    padding: 6px 12px;
    min-height: 16px;
    background: {p.surface};
}}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {p.text_muted};
    margin-right: 10px;
}}
QComboBox:on {{ border-color: {p.accent}; }}   /* popup open */
QComboBox QAbstractItemView {{
    background: {p.card};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 4px;
    outline: none;
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
}}
/* A comfortable click target per row — the default rows are cramped, which is
   half of why picking a value felt fiddly. */
QComboBox QAbstractItemView::item {{
    min-height: 26px;
    padding: 4px 10px;
    border-radius: 6px;
}}
QComboBox QAbstractItemView::item:hover {{
    background: {p.card_hover};
    color: {p.text};
}}
QComboBox QAbstractItemView::item:selected {{
    background: {p.accent};
    color: {p.accent_text};
}}
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {p.border};
    border-radius: 4px;
    background: {p.window};
}}
QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; }}
QCheckBox::indicator:disabled {{ background: {p.border}; }}

/* ------------------------------------------------------------- progress -- */
QProgressBar {{
    background: {p.window};
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {p.accent};
    border-radius: 5px;
}}

/* ------------------------------------------------------------ drop zone -- */
/* Styled by a dynamic `state` property (see DropZone._set_state) rather than
   pseudo-states: Qt has no :drag-over, and a drag is not a hover. */
#DropZone {{
    background: {p.window};
    border: 2px dashed {p.border};
    border-radius: 12px;
}}
#DropZone[state="active"] {{
    background: {p.card_hover};
    border: 2px dashed {p.accent};
}}
#DropZone[state="disabled"] {{
    background: {p.window};
    border: 2px dashed {p.border};
}}
#DropZoneIcon {{
    font-size: 22px;
    color: {p.text_muted};
    background: transparent;
}}
#DropZone[state="active"] #DropZoneIcon,
#DropZone[state="active"] #DropZoneTitle {{
    color: {p.accent};
}}
#DropZoneTitle {{
    font-size: 14px;
    font-weight: 600;
    color: {p.text};
    background: transparent;
}}
#DropZoneHint {{
    font-size: 11px;
    color: {p.text_muted};
    background: transparent;
}}
#DropZone[state="disabled"] #DropZoneTitle,
#DropZone[state="disabled"] #DropZoneHint,
#DropZone[state="disabled"] #DropZoneIcon {{
    color: {p.text_muted};
}}

/* -------------------------------------------------------------- console -- */
#Console {{
    background: {p.console_bg};
    color: {p.console_text};
    border: 1px solid {p.border};
    border-radius: 10px;
    padding: 10px;
    font-family: "JetBrains Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace;
    font-size: 12px;
    selection-background-color: {p.accent};
}}

/* --------------------------------------------------- lists and tables --- */
QListView, QTableView, QTreeView {{
    background: {p.card};
    border: 1px solid {p.border};
    border-radius: 10px;
    outline: none;
    gridline-color: {p.border};
    alternate-background-color: {p.card_hover};
}}
QListView::item, QTableView::item {{
    padding: 8px 10px;
    border-bottom: 1px solid {p.border};
}}
QListView::item:selected, QTableView::item:selected {{
    background: {p.accent};
    color: {p.accent_text};
}}
QHeaderView::section {{
    background: {p.surface};
    color: {p.text_muted};
    border: none;
    border-bottom: 1px solid {p.border};
    padding: 9px 10px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
}}
QTableView {{ selection-background-color: {p.accent}; }}
QTableCornerButton::section {{ background: {p.surface}; border: none; }}

/* ------------------------------------------------------------ scrollbar -- */
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 4px 2px;
}}
QScrollBar::handle:vertical {{
    background: {p.border}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.text_muted}; }}
QScrollBar:horizontal {{
    background: transparent; height: 10px; margin: 2px 4px;
}}
QScrollBar::handle:horizontal {{
    background: {p.border}; border-radius: 4px; min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* --------------------------------------------------------------- banner -- */
#Banner {{
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 12px;
    font-weight: 600;
}}
#EmptyState {{
    color: {p.text_muted};
    font-size: 13px;
    background: transparent;
}}
/* A plain label that must sit flush on its parent (no panel fill) and read as a
   caption. Shared by the uploader scope line, a checklist row label and the
   status-pill word — none of which carry their own colour. */
#FlatLabel {{
    background: transparent;
    font-weight: 600;
}}

/* ----------------------------------------------------------------- chip -- */
/* A rounded status pill — the dashboard's parse-cache read-out. Colour is set
   inline per state (success/warning); this owns only the shape and metrics so the
   pill looks identical whatever colour it carries. */
#Chip {{
    border-radius: 11px;
    padding: 3px 12px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.3px;
}}
"""
