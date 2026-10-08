"""Export copy of the compiled deliverables into a client/year tree.

``output/`` stays exactly as the pipeline and the uploader know it (its paths are
the upload ledger's keys). This module only COPIES each compiled PDF and its JSON
sidecar into a second, human-browsable tree::

    <export.dir>/PDF/<CLIENT>/<YYYY>/<CLIENT>_<YYYY>-<MM>.pdf
    <export.dir>/JSON/<CLIENT>/<YYYY>/<CLIENT>_<YYYY>-<MM>.json

Rules:

* ``<CLIENT>`` is the ``output/<Client>`` folder name; the month comes from the
  sidecar's ``reporting_period``, falling back to the filename's month token — the
  same two sources, in the same order, as ``uploader._sidecar_period_start``.
* Only months >= ``export.from_month`` (``"YYYY-MM"``) are exported.
* A target whose bytes already match (SHA-256) is left alone. A changed one is
  written to a temp file in the same folder and swapped in with ``os.replace``.
  A file held open by a viewer (``PermissionError`` on Windows) is reported and the
  run continues.
* Two sources mapping to one target: both are refused, neither is written.
* NOTHING is ever deleted. A file in the export tree that no current source maps to
  is listed as an orphan on stdout and left in place.

Stdout shape: every line starts with two or four spaces and the word ``Export`` and
never carries ``[...]`` or ``->``, so none of the GUI's progress patterns
(``gui/services/progress.py``) can claim it.

I/O contract
------------
export_reports(settings, log=print) -> ExportResult | None   # None when disabled
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..naming import AZ_MONTHS, MONTH_ABBR

#: Defaults when the ``export`` block (or one of its keys) is absent.
DEFAULT_DIR = "reports"
DEFAULT_FROM_MONTH = "2026-01"

_AZ_MONTH_NUMBER = {name.casefold(): num for num, name in AZ_MONTHS.items()}
_ABBR_MONTH_NUMBER = {abbr.casefold(): num for num, abbr in MONTH_ABBR.items()}

#: (sub-folder, extension) of each exported kind, in print order.
_KINDS = (("PDF", ".pdf"), ("JSON", ".json"))


@dataclass
class ExportResult:
    """What one export pass did; every list holds display strings."""

    copied: list[str] = field(default_factory=list)       # new target written
    unchanged: list[str] = field(default_factory=list)    # target already identical
    overwritten: list[str] = field(default_factory=list)  # target replaced
    orphans: list[str] = field(default_factory=list)      # in the tree, no source
    failed: list[str] = field(default_factory=list)       # refused or not written

    def summary(self) -> str:
        return (f"  Export: copied {len(self.copied)}, unchanged {len(self.unchanged)}, "
                f"overwritten {len(self.overwritten)}, orphan {len(self.orphans)}, "
                f"failed {len(self.failed)}")


def sidecar_period(sidecar: Path) -> _dt.date | None:
    """First day of a sidecar's reporting month, or ``None`` when undatable.

    Mirrors ``uploader._sidecar_period_start`` (uploader.py is a root script and is
    not imported here): ``reporting_period`` ("Dekabr 2025") first, then the
    filename's ``_<MON>_<YYYY>`` token.
    """
    try:
        with open(sidecar, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = None
    if isinstance(data, dict):
        parts = str(data.get("reporting_period", "") or "").split()
        if len(parts) == 2:
            month = _AZ_MONTH_NUMBER.get(parts[0].casefold())
            if month and len(parts[1]) == 4 and parts[1].isdigit():
                return _dt.date(int(parts[1]), month, 1)
    tokens = sidecar.stem.rsplit("_", 2)
    if len(tokens) == 3:
        month = _ABBR_MONTH_NUMBER.get(tokens[1].casefold())
        if month and len(tokens[2]) == 4 and tokens[2].isdigit():
            return _dt.date(int(tokens[2]), month, 1)
    return None


def target_name(client: str, period: _dt.date, ext: str) -> str:
    """``<CLIENT>_<YYYY>-<MM><ext>``."""
    return f"{client}_{period.year:04d}-{period.month:02d}{ext}"


def _parse_from_month(value: object) -> _dt.date:
    text = str(value if value is not None else DEFAULT_FROM_MONTH).strip()
    year, _, month = text.partition("-")
    if not (len(year) == 4 and year.isdigit() and month.isdigit() and 1 <= int(month) <= 12):
        raise ValueError(f"export.from_month must be 'YYYY-MM', got {text!r}")
    return _dt.date(int(year), int(month), 1)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sidecars(output_dir: Path) -> list[Path]:
    """Compiled sidecars directly under ``output/<Client>/``, sorted."""
    return sorted(p for p in output_dir.glob("*/compiled_monthly_report_*.json")
                  if not p.name.startswith(".") and p.parent.name != "failures")


def _copy_one(src: Path, dst: Path, rel: str, result: ExportResult,
              log: Callable[[str], None]) -> None:
    """Copy ``src`` to ``dst`` unless identical; atomic swap; never raises."""
    try:
        exists = dst.is_file()
        if exists and _sha256(src) == _sha256(dst):
            result.unchanged.append(rel)
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f".{dst.name}.export-tmp")
        shutil.copyfile(src, tmp)
        try:
            os.replace(tmp, dst)
        except OSError:
            # Our own temp file only; the operator's target is untouched.
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
    except PermissionError as exc:
        result.failed.append(rel)
        log(f"    Export failed (file in use?): {rel} — {exc.__class__.__name__}")
        return
    except OSError as exc:
        result.failed.append(rel)
        log(f"    Export failed: {rel} — {exc.__class__.__name__}: {exc}")
        return
    if exists:
        result.overwritten.append(rel)
        log(f"    Export overwritten: {rel}")
    else:
        result.copied.append(rel)


def export_reports(settings, log: Callable[[str], None] = print) -> ExportResult | None:
    """Run one export pass per ``settings.raw['export']``; ``None`` when disabled.

    Disabled (the default) means no output at all and no folder created.
    """
    cfg = (settings.raw or {}).get("export") or {}
    if not bool(cfg.get("enabled", False)):
        return None

    root = Path(cfg.get("dir") or DEFAULT_DIR)
    if not root.is_absolute():
        root = Path(settings.project_root) / root
    from_month = _parse_from_month(cfg.get("from_month", DEFAULT_FROM_MONTH))
    output_dir = Path(settings.output_dir)
    result = ExportResult()

    # Plan every (source, target) first so a collision refuses BOTH sources
    # before anything is written.
    planned: dict[Path, list[tuple[Path, str]]] = {}
    for sidecar in _sidecars(output_dir):
        client = sidecar.parent.name
        period = sidecar_period(sidecar)
        if period is None:
            result.failed.append(sidecar.name)
            log(f"    Export skipped (undatable): {client}/{sidecar.name}")
            continue
        if period < from_month:
            continue
        for sub, ext in _KINDS:
            src = sidecar.with_suffix(ext)
            dst = root / sub / client / f"{period.year:04d}" / target_name(client, period, ext)
            planned.setdefault(dst, []).append((src, f"{client}/{src.name}"))

    targets: set[Path] = set(planned)
    for dst in sorted(planned):
        sources = planned[dst]
        rel = dst.relative_to(root).as_posix()
        if len(sources) > 1:
            names = ", ".join(sorted(label for _, label in sources))
            result.failed.extend(label for _, label in sources)
            log(f"    Export refused (2+ sources for {rel}): {names}")
            continue
        src, label = sources[0]
        if not src.is_file():
            result.failed.append(label)
            log(f"    Export missing source: {label}")
            continue
        _copy_one(src, dst, rel, result, log)

    for sub, _ext in _KINDS:
        tree = root / sub
        if not tree.is_dir():
            continue
        for path in sorted(tree.rglob("*")):
            if path.is_file() and path not in targets and not path.name.endswith(".export-tmp"):
                result.orphans.append(path.relative_to(root).as_posix())
    for rel in result.orphans:
        log(f"    Export orphan (no source, left in place): {rel}")

    log(result.summary())
    return result
