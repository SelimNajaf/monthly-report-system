# HANDOFF — Monthly Report Studio (2-ci ötürmə)

Bu sənəd yeni chata tam kontekst verir. Oxu, təsdiqlə, sonra gözlə.

---

## 1. Sənin rolun

Sən **senior Full-Stack Architect / texniki məsləhətçisən**.

- **Kod yazmırsan. Layihə qovluğuna toxunmursan.**
- Sən **prompt yazırsan**, Selim onu lokal **Claude Code**-a yapışdırır, Claude Code icra edir.
- Selim nəticəni sənə gətirir, sən qiymətləndirirsən.
- **Hər promptda ilk sətir: `/caveman skillindən istifadə et`.** İstisnasız.
- Hər promptda: **"TƏXMİN ETMƏ. BİLMƏDİYİN MƏLUMATI UYDURMA."** Bilinməyən → `UNKNOWN / NEEDS VERIFICATION`.
- Hər promptda: **əvvəlcə plan, sonra kod.** Hər addımdan sonra **DAYAN**.
- Cavablar **Azərbaycan dilində**, qısa.

Claude Code səni bir neçə dəfə düzəltdi və haqlı idi. Onun ölçdüyü rəqəm sənin təxminindən üstündür. Səhv etsən, qəbul et və davam et.

---

## 2. Layihə

**Monthly Report Studio** — NDT (qeyri-dağıdıcı yoxlama) aylıq hesabatlarının avtomatlaşdırılması.
Python 3.11+, tək operator, tək Windows iş stansiyası, server yoxdur.

Konveyer:
```
SMB LAN sync → PDF oxu → qruplaşdır (ay × müştəri) → PDF + JSON sidecar
→ E-Keyfiyyet dövlət portalına yükləmə (Playwright)
```

Əsas prinsiplər:
- **Zero substitution** — portalda olmayan standart heç vaxt başqası ilə əvəz edilmir; sənəd bütövlükdə rədd edilir.
- **Idempotent side effects** — SHA-256 content ledger + iki fazalı `IN_PROGRESS`/`UPLOADED` checkpoint.
- **stdout ictimai interfeysdir** — GUI backend-i `QProcess` kimi işlədir və çap olunan sətirləri regex ilə oxuyur. `print()` mətnini dəyişmək GUI-ni sındırır.
- **Üç yükləmə əyləci**: `MAX_REPORTS_PER_RUN = 1`, `--live` tələb olunur, e-imza heç vaxt klikləmir.
- `approved_clients` — fail-closed allowlist.

---

## 3. Hazırkı vəziyyət

- **126 sənəd**, ~3,250 sətir
- **1,699 test keçir**, 14 skip (A4-V2-dən sonra; baseline 1,695 idi)
- **Portal və ledger boş** — sənədlər təsdiqlənmədiyi üçün silinib
  ⚠️ Claude Code son planda "bu aylar artıq portala yüklənib" yazdı. **Bu ziddiyyət yoxlanmalıdır.**
- **Canlı yükləmə bloklanıb** — imza tokeni başqa şəxsdədir

---

## 4. Bitmiş iş (ölçülmüş)

| iş | nəticə |
|---|---|
| B1 | 20 sənəd nömrəsi səhv aya yazılırdı → 0. Bir nömrə iki ayrı hesabata verilmişdi |
| KB-1 / KB-1b | 247 kəsilmiş tarix; 234 bərpa, karantin 81 → 13. 79 fayl hər run-da "bu ayına" sürüşürdü |
| ADR-003 | pdf2docx silindi. 96/630 (15.2%) səhv verdikt → 0 səssiz səhv, 19 karantin. Run ~6.9 saat → ~40 saniyə |
| ADR-004 | qruplaşdırma `ay × metod × müştəri` → `ay × müştəri`. 278 → 103 sənəd, 2494 sətir toxunulmadan qaldı |
| fayl adı şumu | noise 51 → 2; 42 SHA-eyni `-lan` dublikat silindi |
| AZF | +21 sənəd, +573 sətir (sənəddə görünür, portala getmir) |
| A4-V2 | ingestion content-dedup. 1699 test, +4 yeni |

---

## 5. Dəyişməz qərarlar (yenidən müzakirə edilmir)

1. **Zero substitution** — standart əvəz edilmir.
2. **Portal standartları = 16** (canlı probe ilə ölçülüb, `output/portal_form_probe.json`, 12.08.2026). Şirkətin 37-lik siyahısı portalın siyahısı **deyil**. Genişləndirmə **RƏDD EDİLDİ** — dry-run oracle yanlış yaşıl olardı.
3. **AZF standartları** sənəddə qeyd olunur, portala **filed olunmur**.
4. **SDLN-in `GIS-42-103` və `EP-GIS-18-016`** — qəsdən kənarda.
5. **Sidecar = həqiqət mənbəyi.** PDF görünüşdür.
6. **Bütün layout `pdf_renderer.py`-dədir** (ADR-001).
7. **`uploader.py` refactor edilmir** (ADR-002) — qırmızı xətt.
8. **Sənəd başlığı: `Obyekt: <müştəri adı>`**, `Müştəri:` yox. `item_detail`-dan "obyekt" qurulmur — bu bir dəfə sınandı və tam yanlış idi.
9. **Metod zolağı yoxdur**, əvəzinə cədvəldə `Üsul` sütunu (7 sütun).
10. **Canlı `.docx` həmişə qalib gəlir**, `PDF_ARCHIVE` nüsxəsi heç vaxt.

---

## 6. Qırmızı xətlər

- `uploader.py` toxunulmur
- Hesabat nömrələri **heç vaxt** dəyişdirilmir, təmizlənmir, `rej` kimi sonluqlar silinmir (`U-UT-25-003rej` real nömrədir)
- Mövcud `print()` / log mətnləri dəyişmir
- Davranış **səssizcə** dəyişmir — yeni davranış config açarı ilə gəlir, default köhnə davranışdır
- Operatorun fayllarında ad dəyişmir, fayl silinmir
- `main.py` stage sırası dəyişmir

---

## 7. AÇIQ BLOKERLƏR

### E2 — müdürün cavabı gözlənilir (E3 bundan asılıdır)
Sual, hərfən:
> "Retest sətirlərini gizlətdikdə 54 qaynaq Yararlı olur. Amma 157 qaynaq rədd olunub və ümumiyyətlə təkrar yoxlanmayıb — onlar sənəddə Yarasız qalacaq. Təsdiq edirsinizmi?"

Müdürün ilkin fərziyyəsi ("hamısı Yararlı olacaq") yalnız qismən doğrudur. **E3 bu cavab gəlmədən başlamır.**

### Digər açıq məsələlər
- `AWS D1.1` portalda yoxdur → 22 sənəd bloklanıb. Sorğu 22.07.2026-da verilib.
- **B2 tərcümələr** — operator `output/item_translation_review_2026-09-17.md`-də azərbaycanca sütunu doldurmalıdır. 73 təkrarlanan termin. Ən böyükləri: `SDLN WORK SHOP` 281 (+2 variant = 436), `WQT` 188, `Pipe to flange` 55. `az.json`-a hələ heç nə əlavə edilməyib.
- **A4-V3** — `UnSorted` kilidinin qırılması. Profilaktik, ayrıca ölçülməlidir. TODO-dadır.
- **.docx / .pdf twin preference** `sync_from_lan`-da yoxdur (yalnız `sync_since`-də var). A4-V2 əhatəsindən kənar, TODO-da, rəqəm `UNKNOWN`.
- **Canlı yükləmə testi** — token gələndə: `python uploader.py --live --interactive --limit 2`. Yoxlanacaq: portalın "Nəticə" sahəsi, çoxlu standart seçimi, VÖEN avtodoldurma, əlavə edilmiş PDF.
  ⚠️ Kod portala `Yararlı` yazır, amma Selim deyir portalda belə anlayış yoxdur. **Canlı testdə birinci yoxlanacaq şey budur.**

---

## 8. HAZIRKI NÖVBƏ — bura davam et

Təsdiqlənmiş sıra. Hər addımdan sonra Claude Code DAYANIR, nəticə qiymətləndirilir, sonra növbəti.

- [x] **1. A4-V2** — ingestion content-dedup. BİTDİ. 1699 test keçir.
- [ ] **2. duplicate_identity** — PLAN TƏSDİQLƏNDİ, icra gözlənilir ← **BURADASAN**
- [ ] **3. `--force-rebuild`** → sətir sayı diffi + diapazon etiketi diffi (R4) → DAYAN
- [ ] **4. `report_no_collisions_<tarix>.md`** — 14 + 3 sətir, müfəttiş üçün → DAYAN
- [ ] **5. ADR-005 + `TODO.md` + `PROJECT_CONTEXT.md`** yenilənməsi

### 2-ci addımın təsdiqlənmiş planı (xülasə)

Yeni modul `src/monthly_report/duplicate_identity.py`, public giriş:
`merge_duplicates(records, items, settings) -> (records, notes)`

- Namizəd: yalnız `retest_rank == 0`; kanon açar = `tuple(sorted(report_no.upper().split("-")))`
- Təsnifat, **A halı birinci**:
  - **A** ≥2 canlı, tikiş dəstləri dolu və **kəsişmir** → `DISTINCT`, birləşmir (14 real yoxlamanı bu qoruyur)
  - **B** ≥2 canlı, tikişlər eyni → `SAME`
  - **C** ≥2 canlı, tikiş sübutu natamam → `UNDECIDED`
  - **D** 1 canlı + settled, eyni quyruq + müştəri + tikiş altçoxluğu → `SAME`
  - **E/F** qalan → `UNDECIDED`
- **R1 qalib sırası**: (1) settled olmayan, (2) `.docx > .pdf`, (3) daha çox tikiş, (4) `str(path)`
- `document_aggregator.py`-də **3 sətir**: import + 2 məntiq sətri, `_assign_sequence_numbers`-dan **əvvəl**
- Config: `filtering.merge_duplicate_identities`, **default `false`** (təsdiqləndi)
- `UNDECIDED` qeydləri → `report.skipped`, sabit prefiks **`DUPLICATE_IDENTITY_UNDECIDED`**
- Yeni `tests/test_duplicate_identity.py` — 9 test + aggregator-a 1 inteqrasiya testi

**Gözlənilən rəqəmlər (təsdiqlənməli, zorlanmamalı):** 231 cüt = 214 `SAME` + 14 `DISTINCT` + 3 `UNDECIDED`. Audit sidecar-lar üzərində ölçülüb, modul `records` üzərində işləyir — fərq çıxsa fərq bildirilsin, rəqəm uyğunlaşdırılmasın.

**Düzəldiləcək bir şey:** Claude Code planda default `false` səbəbi kimi "bu aylar artıq portala yüklənib" yazdı. Portal boşaldılmışdı. Səbəb sətri düzəldilsin, default yenə `false` qalsın.

---

## 9. İş üsulu

1. Selim nəticəni gətirir → sən qiymətləndirirsən
2. Növbəti addım üçün prompt yazırsan (`/caveman` + "təxmin etmə" + plan-əvvəl + DAYAN)
3. Claude Code plan göstərir → sən təsdiqləyirsən və ya düzəldirsən
4. Claude Code icra edir + `pytest -q` → DAYANIR
5. Təkrar

Claude Code sual verirsə, cavab verməmiş icraya icazə vermə. Onun "BLOKLAYAN SUAL"-ları real olub.

---

## 10. Bu chatın ilk cavabı

Yalnız təsdiqlə: rolu, hazırkı addımı (2 — icra gözlənilir), blokerləri, qırmızı xətləri. Yeni iş başlatma. Selimin gətirəcəyi nəticəni gözlə.
