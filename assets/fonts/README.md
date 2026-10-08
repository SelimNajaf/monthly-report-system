# Fonts

Place a Unicode TrueType font here that fully covers the **Azerbaijani Latin
alphabet**, including `ə ğ ı İ ö ş ç ü` (both cases).

## Recommended

- **Noto Sans** — `NotoSans-Regular.ttf`, `NotoSans-Bold.ttf`
  (https://fonts.google.com/noto/specimen/Noto+Sans), **or**
- **DejaVu Sans** — `DejaVuSans.ttf`, `DejaVuSans-Bold.ttf`
  (ships with many systems; SIL/Bitstream Vera license).

## Why fonts are not committed

Font binaries are intentionally **not** checked in (licensing + repo size). The
PDF renderer reads the font file names from `config/settings.yaml`
(`fonts.regular` / `fonts.bold`) and will fail fast with a clear message if the
referenced TTF is missing from this folder.

Expected default filenames (see `config/settings.yaml`):

```
assets/fonts/NotoSans-Regular.ttf
assets/fonts/NotoSans-Bold.ttf
```
