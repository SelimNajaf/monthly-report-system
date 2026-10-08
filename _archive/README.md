# _archive

Retired backups, stale output trees and retired tooling, moved here from the repo root
on 2026-09-28 (F3, `docs/INVENTORY_2026-09-28.md` §2.3–2.4). Every move was a same-disk
rename; byte and file counts were compared before and after and matched. Nothing was
deleted or edited. The folder is gitignored (`_archive/*`) — it holds real client documents
and copies of the upload ledger — except this README and `claude-skills-graphify/`, whose
files were already tracked and were moved with `git mv`.

Dates: "files" = oldest…newest file mtime inside the folder.

| folder | what it is | came from | files (dates) | size |
|---|---|---|---|---|
| `output_backup/` | 6 pre-change snapshots of `output/` (2026-09-03 pre-obyekt-refactor … 2026-09-17 pre-task11); the first 5 also hold copies of `.upload_state.json` and `output/upload_status.json` | `./output_backup/` | 3021 (2026-07-17…2026-09-17) | 167M (166 562 884 B) |
| `output_backup_20260918/` | snapshot of `output/` | `./output_backup_20260918/` | 305 (2026-07-17…2026-09-18) | 15M (14 887 936 B) |
| `output_backup_20260918b/` | snapshot of `output/` — **renamed**, see note below | `./output_backup_20260921/` | 305 (2026-07-17…2026-09-18) | 15M (14 887 633 B) |
| `output_backup_20260924_1029/` | snapshot of `output/` | `./output_backup_20260924_1029/` | 309 (2026-07-17…2026-09-21) | 16M (15 022 103 B) |
| `output_backup_20260924_1220/` | snapshot of `output/` (newest backup) | `./output_backup_20260924_1220/` | 314 (2026-07-17…2026-09-24) | 16M (15 081 546 B) |
| `output_stale/` | retired PDF+JSON pairs whose group no longer exists, moved out of `output/` by hand (6 subfolders, 2026-09-04 … 2026-09-08_adr004) | `./output_stale/` | 1755 (2026-07-24…2026-09-08) | 89M (88 144 914 B) |
| `graphify-out/` | graphify knowledge graph built 2026-07-21 from commit `3dd0e50`; stale (does not cover ADR-003..009 code) | `./graphify-out/` | 1128 (2026-07-14…2026-07-21) | 29M (27 738 833 B) |
| `claude-skills-graphify/` | project copy of the graphify skill, v0.9.15 (a global copy exists at `~/.claude/skills/graphify`, v0.9.30); tracked in git | `./.claude/skills/graphify/` | 10 (2026-07-14) | 101K (80 977 B) |

**Why `output_backup_20260918b`:** the folder was named `output_backup_20260921`, but its
newest file and its own mtime are 2026-09-18 (folder mtime 2026-09-18 14:48 — earlier than
`output_backup_20260918`, 16:02 the same day). The name claimed a date its contents do not
have. It is not a duplicate of `output_backup_20260918`: `diff -rq` found 144 differing
files (inventory §2.3). Hence the same date plus a `b` suffix.

`scripts/prune_lan_duplicates.py --rename-audit` now defaults to
`_archive/output_backup/2026-09-17_pre-task11/pdf_renames_{today}.txt`.

Selim silinməsinə qərar verənə qədər saxlanılır.
