"""``prune_lan_duplicates --rename-audit`` defaults into ``_archive/``, not the repo root.

The Task 11 snapshot the audit trail belongs to moved from ``output_backup/`` to
``_archive/output_backup/`` on 2026-09-28. ``write_rename_audit`` creates missing
parents, so a stale default would not fail — it would silently re-create
``output_backup/`` at the root. The default path is therefore pinned here.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

import prune_lan_duplicates                                       # noqa: E402


def test_rename_audit_defaults_under_archive(tmp_path, monkeypatch):
    written: list[Path] = []
    monkeypatch.setattr(prune_lan_duplicates, "write_rename_audit",
                        lambda out_path, rows, today, **kw: written.append(out_path)
                        or out_path)
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    assert prune_lan_duplicates.main(["--rename", "--input-dir", str(input_dir)]) == 0

    assert len(written) == 1
    audit = written[0]
    assert audit.parent == _ROOT / "_archive" / "output_backup" / "2026-09-17_pre-task11"
    assert re.fullmatch(r"pdf_renames_\d{4}-\d{2}-\d{2}\.txt", audit.name)
