/caveman skillindən istifadə et.
TƏXMİN ETMƏ. BİLMƏDİYİN MƏLUMATI UYDURMA.
Bilinməyəni "UNKNOWN / NEEDS VERIFICATION" kimi qeyd et.

# F3 — Nizamlama (köçürmə, arxiv, bölmə). Heç nə silinmir.

Əsas: `docs/INVENTORY_2026-09-28.md`. Bu mərhələdə `CLAUDE.md` və `INDEX.md` yazılmır, onlar F4-dədir.

## Selimin qərarları

- **Q1.** `generate_inspector_worksheet.py` yerində qalır.
- **Q2.** Root `HANDOFF.md` və `Claude outputs/HANDOFF*.md` → `docs/history/handoffs/`.
  - `Claude outputs/AGENT_BRIEF.md` hələlik `docs/history/handoffs/`-yə köçür. F4-də `CLAUDE.md`-yə birləşəcək.
- **Q3.** `PROJECT_CONTEXT.md` → `docs/history/PROJECT_CONTEXT_2026-09-03.md` (`git mv`). Məzmunu dəyişmir.
- **Q4.** `TODO.md` iki hissəyə bölünür:
  - Root `TODO.md` — yalnız açıq bəndlər, qısa. Hər bənd bir-iki sətir, jurnala istinadla (`docs/history/TODO_journal.md#...`).
  - `docs/history/TODO_journal.md` — köhnə faylın tam məzmunu, **bayt-bayt**. Əvvəlcə `git mv TODO.md docs/history/TODO_journal.md` et, sonra yeni `TODO.md` yarat. Belə edəndə tarixçə itmir.
  - Açıq/bağlı saylarını yaz. Heç bir bəndi itirmə: yeni `TODO.md`-dəki hər bənd jurnalda olmalıdır.
- **Q5.** `graphify-out/` → `_archive/graphify-out/`, `.claude/skills/graphify/` → `_archive/claude-skills-graphify/`.
  - Tracked-dirsə `git mv`, deyilsə `mv`.
  - Başqa skill, hook və ya config graphify-ə istinad edirsə, sadala. Özün dəyişmə.
- **Q6.** `skills-lock.json` yerində qalır.
- **Q7.** `SKILLS_MANIFEST.md`-nin məzmunu `.agents/skills/README.md`-nin sonuna "Manifest" başlığı ilə əlavə olunur. Əvvəl dublikat yoxla. Sonra `SKILLS_MANIFEST.md` → `docs/history/` (`git mv`).
- **Q8.** `config/fields.yaml`-a toxunulmur.
- **Q9.** `TODO.md`:339 (.exe) və :341 (LAN mapping): hər biri üçün kod və ya README-dən fayl:sətir sübutu göstər. Sübut varsa, yeni `TODO.md`-yə salma, jurnalda "bağlandı <tarix> — sübut" qeydi əlavə et. Sübut yoxdursa, açıq qalır.
- **Q10.** `scripts/prune_lan_duplicates.py:439` default yolu `_archive/output_backup/` olur. Bir test əlavə et və ya mövcud testi yenilə.

## Backup-lar

- `output_backup/`, `output_stale/`, `output_backup_2026*` (4 ədəd) → `_archive/` altına, adları dəyişmədən.
  - İstisna: `output_backup_20260921` qovluğunun məzmunu 09-18 tarixlidir. Onu `_archive/output_backup_20260918b/` adı ilə köçür və səbəbini `_archive/README.md`-yə yaz.
- `_archive/README.md` yarat. Hər qovluq üçün bir sətir: nədir, haradan gəlib, tarix, ölçü. Sonda bu qeyd olsun: "Selim silinməsinə qərar verənə qədər saxlanılır."
- Köçürmədən **əvvəl** `.gitignore`-a `_archive/` əlavə et. Amma `_archive/README.md` izlənsin: `!_archive/README.md`. CRLF saxla.
- Köçürmə eyni diskdə rename olmalıdır, kopya deyil. Əvvəl və sonra ölçünü müqayisə et.
- Root və `tests/`-dəki `__pycache__` qovluqlarına toxunma. Onlar gitignore-dadır və avtomatik yaranır.

## `docs/` strukturu

```
docs/
  INVENTORY_2026-09-28.md
  history/
    PROJECT_CONTEXT_2026-09-03.md
    TODO_journal.md
    SKILLS_MANIFEST.md
    handoffs/
```

`Claude outputs/` qovluğu qalır: bu, mənim prompt fayllarım üçündür. İçindəki handoff-lar köçdükdən sonra orada nə qalırsa, siyahısını ver.

## Köçürmədən sonra yoxla

1. Hər köçürülən tracked fayl üçün köhnə yolun kodda, testdə, README-də, `CLI_MANUAL.md`-də və ADR-lərdə istinadlarını `git grep` ilə tap. Kod və test istinadı varsa, DAYAN və göstər. Sənəd istinadlarını yeni yola yenilə və siyahısını ver.
2. `python -m pytest -q` — əvvəlki nəticə 1914/14/0. `collect-only` 1928 göstərir; fərqi izah et.
3. `test_cli_manual_sync` yaşıl olmalıdır.
4. Root-un yeni `ls` siyahısını ver, əvvəlki ilə müqayisədə.

## Commit

Commit iki hissəyə bölünür:

- **(a)** `chore(layout): archive backups/graphify, move history docs, split TODO` — köçürmələr, `.gitignore`, `_archive/README.md`, TODO bölünməsi, SKILLS_MANIFEST birləşməsi.
- **(b)** `fix(scripts): prune_lan_duplicates default backup path → _archive/` — Q10 və testi.

Push etmə. `git log --oneline -3`. Sonra DAYAN.

## Qırmızı xətlər

- Fayl silinmir. Yalnız `git mv` və ya `mv` işlədilir. Hədəfdə eyni adlı fayl varsa, DAYAN.
- `input/`, `output/`, `.state/`, `.parse_cache/`, `.browser_profile/`, `.upload_state*.json`, `config/settings.yaml` toxunulmazdır.
- Kod dəyişmir. Yeganə istisna Q10-dur.
- `uploader.py`, `main.py` və `print()` mətnləri dəyişmir.
- Root `.py` faylları yerində qalır.
