/caveman skillindən istifadə et.
TƏXMİN ETMƏ. BİLMƏDİYİN MƏLUMATI UYDURMA.
Bilinməyəni "UNKNOWN / NEEDS VERIFICATION" kimi qeyd et.

# F1 — Layihə inventarı (yalnız oxu, heç nə köçürmə və dəyişmə)

Məqsəd: layihəni sonradan nizamlamaq və `CLAUDE.md` / `INDEX.md` hazırlamaq üçün hər qovluğun və root faylının təsnifatı. Bu mərhələdə **heç bir fayl köçürülmür, silinmir və ya dəyişdirilmir**. Yeganə çıxış `docs/INVENTORY_<YYYY-MM-DD>.md` faylıdır.

## Əhatə

- Root-dakı hər fayl və qovluq, gizlilər daxil.
- `src/monthly_report/`, `scripts/`, `tests/`, `config/`, `architecture/`, `standarts/`, `assets/`, `images/`, `samples/`, `.claude/`, `.agents/`, `Claude outputs/` — 1 səviyyə dərinlikdə.
- `input/` və `output/` daxilinə enmə. Yalnız ölçü və alt qovluq adları.

## Hər sətir üçün sütunlar

| path | növ | ölçü | git-də? | son dəyişiklik | kim istinad edir | sinif | təklif |
|---|---|---|---|---|---|---|---|

- **git-də?** `git ls-files` və `git check-ignore` ilə yoxla: `tracked` / `ignored` / `untracked`.
- **kim istinad edir:** kod, test, GUI, pyproject və skriptlərdə adı keçən yerlər (fayl:sətir, ən çox 3). Axtarış `grep`/`git grep` ilə olsun, təxmin olmasın. İstinad yoxdursa, "yoxdur" yaz.
- **sinif** (biri):
  - `entrypoint` — main.py, uploader.py, gui_launcher.py
  - `core-code`
  - `helper-script`
  - `test`
  - `config`
  - `docs-current` — hazırkı vəziyyəti təsvir edir
  - `docs-stale` — köhnəlmiş handoff, jurnal
  - `generated` — cache, graph, pycache
  - `backup`
  - `operator-data` — input, output, ledger, state
  - `agent-tooling` — .claude, .agents, skills
- **təklif** (biri): `keep` / `move → <yer>` / `archive` / `merge → <fayl>` / `split` / `UNKNOWN`. Hər təklifə bir cümlə səbəb yaz.

## Xüsusi suallar — hər birinə sübutla cavab ver

1. **Root-dakı .py faylları:** hər birini başqa yerə köçürsək nə sınar? GUI (`app_paths.py`, `job_runner.py`, `worker_entry.py`), testlər, `pyproject.toml`, `setup.ps1`/`setup.sh`, `CLI_MANUAL.md` sinxron testi. Fayl:sətir göstər.
2. **Böyük sənədlər:** `PROJECT_CONTEXT.md` (104K), `TODO.md` (68K), `README.md` (42K), `CLI_MANUAL.md` (22K), `HANDOFF.md`, `SKILLS_MANIFEST.md`.
   - Hər biri nə üçündür?
   - Sonuncu faydalı yeniləmə nə vaxt olub?
   - Bir-birini təkrarlayan bölmələr hansılardır? Başlıq səviyyəsində müqayisə et.
   - `TODO.md`-də neçə bənd açıq, neçəsi bağlıdır?
3. **Backup və köhnə çıxışlar:** `output_backup/`, `output_stale/`, `output_backup_2026*` (4 ədəd), `graphify-out/`, root `__pycache__/`.
   - Ölçü, tarix, ignore statusu.
   - Kod bunlardan birinə istinad edirmi? (`scripts/prune_lan_duplicates.py` `output_backup`-a istinad edir — nə üçün?)
4. **graphify:**
   - `.claude/skills/graphify` skill-i agentə `graphify-out/`-u birinci mənbə kimi işlətməyi deyir.
   - `graphify-out` 2026-07-21 tarixlidir. Qraf indiki kodla nə qədər uyğundur? Məsələn, `report_no_mismatch.py`, `duplicate_identity.py`, ADR-006–009 qrafda varmı?
   - Köhnə qraf agenti yanıldırmı? Sübutla göstər.
5. **Skills:**
   - `.agents/skills`-də 17 skill var, `.claude/skills`-də yalnız graphify. `skills-lock.json`-da nə var?
   - `/caveman` Claude Code-da haradan yüklənir? Sübut göstər; tapılmasa UNKNOWN.
6. **`Claude outputs/`:** hansı faylları hələ aktualdır, hansıları köhnəlib?
7. **`samples/`, `standarts/`, `images/`, `assets/`:** kod tərəfindən işlədilirmi?
8. **Kök səviyyədə gözlənilməyən və ya dağınıq yerləşən hər şey.**

## Çıxış

1. `docs/INVENTORY_<YYYY-MM-DD>.md`:
   - yuxarıdakı cədvəl;
   - xüsusi sualların cavabları;
   - sonda **"Təklif olunan hədəf struktur"** — ağac şəklində, ən çox 40 sətir.
2. Hədəf strukturda bu qaydalara əməl et:
   - kod faylları (`entrypoint`, `core-code`) yerində qalır, köçürmə ancaq sübut varsa təklif olunur ki, heç nə sınmır;
   - `operator-data` yerində qalır;
   - backup-lar vahid `_archive/` altına yığılır (gitignored); silinmir;
   - köhnəlmiş sənədlər `docs/history/` altına;
   - root-da yalnız entrypoint-lər, config faylları və bir neçə əsas sənəd qalır.
3. Söhbətdə qısa xülasə:
   - diskə görə ən böyük 5 israf;
   - agent üçün ən çaşdırıcı 5 şey;
   - Selimin qərar verməli olduğu suallar siyahısı.

`docs/` qovluğu yoxdursa, yarat. Başqa heç nə yaratma, dəyişmə, köçürmə. Git əmrləri yalnız oxumaq üçündür. Commit etmə.

Sonra DAYAN.

## Qırmızı xətlər

- `input/`, `output/`, `.state/`, `.parse_cache/`, `.browser_profile/`, `.upload_state*.json` fayllarına toxunulmur.
- `uploader.py`, `main.py` stage sırası və `print()` mətnləri dəyişmir.
- Fayl silinmir.
