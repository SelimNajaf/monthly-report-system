/caveman skillindən istifadə et.
TƏXMİN ETMƏ. BİLMƏDİYİN MƏLUMATI UYDURMA.
Bilinməyəni "UNKNOWN / NEEDS VERIFICATION" kimi qeyd et.

# F4 — `CLAUDE.md` + `docs/INDEX.md` + sinxron test

Məqsəd: hər yeni Claude Code sessiyası layihəni tam oxumadan başa düşsün. `CLAUDE.md` avtomatik yüklənir, `docs/INDEX.md` isə lazım olanda oxunur.

**Mənbələr** (yalnız bunlar, təxmin olmasın):

- `docs/CODE_MAP_2026-09-28.md`
- `docs/INVENTORY_2026-09-28.md`
- `architecture/ADR-001…009`
- `config/settings.example.yaml`
- `CLI_MANUAL.md`
- yeni `TODO.md`
- `docs/history/handoffs/AGENT_BRIEF.md` — yalnız prinsiplər, qırmızı xətlər, lüğət və "yenidən açma" tarixçəsi. Bu fayldan UNC yolu, host adı və başqa şəxslərin adları **köçürülmür**.

Dil: ingiliscə (ADR-lər kimi, token baxımından da qənaətlidir). Azərbaycanca UI mətnləri (`Yararlı`, `Obyekt:`) olduğu kimi qalır.

## 1. `CLAUDE.md` (root, ən çox 150 sətir)

Bölmələr:

1. **What this is** — 5 sətir: NDT hesabatları → ay × müştəri üzrə PDF + JSON sidecar → E-Keyfiyyet portalı. Tək operator, tək Windows stansiyası, server yoxdur.
2. **How to run** — Python versiyası; `.venv` yoxdur, sistem Python-u işlədilir; `python -m pytest -q`, `python main.py --force-rebuild`, `python uploader.py --dry-run --all --limit 200`. `--live` yalnız operatorun açıq icazəsi ilə. Qeyd: `--force-rebuild` LAN-dan yeni fayl gətirə bilər (`Staged N`).
3. **Working rules** — plan → kod → pytest → DAYAN; ölç, təxmin etmə; UNKNOWN; yeni davranış həmişə config açarı arxasında olur, default köhnə davranışdır; hər addımdan sonra dayan.
4. **Red lines** — qırmızı xətlərin tam siyahısı: `uploader.py` (ADR-002), hesabat nömrələri, `print()` mətnləri, stage sırası, operator faylları, `output/`-a nümunə yazmamaq, layout yalnız `pdf_renderer.py`-də, `--live`. `input/`, `output/`, `.state/`, `.parse_cache/`, `.browser_profile/`, `.upload_state*.json`, `config/settings.yaml`.
5. **Core principles** — cədvəl, 6 sətir: zero substitution, idempotent ledger, stdout = public interface, üç upload əyləci, fail-closed, sidecar = həqiqət mənbəyi.
6. **Pipeline map** — CODE_MAP-dəki diaqramın qısa forması (ən çox 12 sətir).
7. **Where things live** — `docs/INDEX.md`, `architecture/`, `TODO.md`, `docs/history/`, `_archive/` (silinmir, ignored).
8. **Known traps** — hər biri bir sətir:
   - CRLF faylları: `sed -i` CRLF-i pozur, python ilə redaktə et;
   - graphify bu layihədə **işlədilmir**, qraf arxivdədir;
   - `test_verdict_regression` hazırda həmişə skip olunur, yəni ADR-003 qapısı işləmir (TODO-ya istinad);
   - portalda əvvəlki run-lardan draft-lar var, "portal boşdur" iddiası sübutsuzdur, ledger 2026-09-04-də sıfırlanıb;
   - `main.py` `gui.services.catalog`-dan import edir;
   - root `.py` faylları `Path(__file__).parent`-dən asılıdır, onları köçürmə;
   - `standarts/` yazılışı qəsdəndir, adını dəyişmə.
9. **Current state** — **dəyişən rəqəm yazma**: test sayı, sənəd sayı və sətir sayı yoxdur. Bunun əvəzinə onları əldə etmək üçün əmrlər yaz (`pytest --collect-only -q | tail -1` və s.).

## 2. `docs/INDEX.md`

- Root-dakı hər element (gizlilər və ignored qovluqlar daxil) üçün bir sətir: nədir və sinfi (INVENTORY-dəki siniflər).
- `src/monthly_report/**`, `scripts/`, root `.py` faylları üçün bir sətir: nə edir və stage. Məlumat CODE_MAP-dən götürülür.
- `config/settings.example.yaml`-dakı `presentation`, `filtering`, `retest` açarları: açar → bir sətir → ADR. Dəyərləri yazma, onlar dəyişir.
- **Known quirks** bölməsi: iki `services/` paketi, `sys.path` hack-i, `theme.py` `assets/stitch`, ölü `config/fields.yaml`, `generate_inspector_worksheet.py`-də hardcode olunmuş adlar (adları yazma), `pdf_twin` docstring-inin köhnəlməsi.
- Hər yol backtick içində yazılır: `` `path` ``. Runtime zamanı yaranan və ya ignored qovluqları `(runtime)` işarəsi ilə qeyd et.

## 3. Sinxron test: `tests/test_index_sync.py`

Test aşağıdakıları yoxlamalıdır:

1. Root-dakı hər element (`.git` istisna) `docs/INDEX.md`-də backtick içində keçir.
2. `src/monthly_report/` altındakı hər `.py` və `scripts/*.py` INDEX-də keçir.
3. INDEX-dəki hər backtick yol mövcuddur. `(runtime)` ilə işarələnənlər istisnadır.
4. `CLAUDE.md` 150 sətirdən uzun deyil.
5. `CLAUDE.md` və INDEX-də sirr nümunəsi yoxdur: `\\\\`, UNC yolu, `gulnara`, 10 rəqəmli VÖEN nümunəsi. Mövcud `test_cli_manual_sync.py` üslubunu təqlid et.

Test uğursuz olanda mesaj açıq olmalıdır, məsələn: "`foo.py` INDEX-də yoxdur — `docs/INDEX.md`-yə bir sətir əlavə et".

## 4. Kiçik uyğunlaşdırmalar (yalnız sənəd)

- `README.md:747-750` graphify paraqrafı → "archived, not used; see `_archive/README.md`".
- README-də `PROJECT_CONTEXT.md`, `HANDOFF.md`, `SKILLS_MANIFEST.md` linkləri → yeni yollar. Hamısını `git grep` ilə tap.
- `TODO.md`-yə iki açıq bənd əlavə et (jurnala da bir sətir):
  - **P0:** portaldakı draft-ların yoxlanması və təmizlənməsi — 14 hesabat, 12-si iki dəfə saxlanıb, köhnə strukturda. Növbəti `--live`-dan əvvəl mütləqdir.
  - **P1:** ADR-003 verdikt qapısının bərpası — CODE_MAP §2.9-dakı variantlar.

## Commit

- `python -m pytest -q` — yeni test daxil. Nəticəni yaz.
- Commit: `docs: CLAUDE.md, docs/INDEX.md, index sync test`. Push etmə.
- `CLAUDE.md`-nin tam mətnini cavabda göstər.

Sonra DAYAN.

## Qırmızı xətlər

- Kod, config, `input/` və `output/` dəyişmir. Yalnız sənəd və yeni test.
- Fayl silinmir və köçürülmür.
- `AGENT_BRIEF.md`, handoff-lar və `Claude outputs/` commit olunmur.
