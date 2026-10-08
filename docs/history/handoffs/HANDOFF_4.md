# HANDOFF — Monthly Report Studio (tam ötürmə, 21.09.2026)

Bu sənəd təkbaşına kifayətdir. Oxu, təsdiqlə, gözlə.

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

Claude Code bir neçə dəfə məni düzəltdi və haqlı idi. Onun ölçdüyü rəqəm sənin təxminindən üstündür. Səhv etsən, qəbul et və davam et.

---

## 2. Layihə

**Monthly Report Studio** — NDT (qeyri-dağıdıcı yoxlama) aylıq hesabatlarının avtomatlaşdırılması. Python 3.11+, tək operator, tək Windows iş stansiyası, server yoxdur.

```
SMB LAN sync → PDF oxu → qruplaşdır (ay × müştəri) → PDF + JSON sidecar
→ E-Keyfiyyet dövlət portalına yükləmə (Playwright)
```

Prinsiplər:
- **Zero substitution** — portalda olmayan standart əvəz edilmir; sənəd bütövlükdə rədd edilir.
- **Idempotent side effects** — SHA-256 ledger + `IN_PROGRESS`/`UPLOADED` checkpoint.
- **stdout ictimai interfeysdir** — GUI `print()` sətirlərini regex ilə oxuyur; mətni dəyişmək GUI-ni sındırır.
- **Üç yükləmə əyləci**: `MAX_REPORTS_PER_RUN = 1`, `--live` tələb olunur, e-imza heç vaxt klikləmir.
- `approved_clients` — fail-closed allowlist.

---

## 3. Hazırkı vəziyyət (ölçülmüş)

| | |
|---|---|
| sənəd | 126 |
| sətir | 3271 (default açarlarla) |
| test | **1737 keçir**, 14 skip |
| commit | **heç nə commit edilməyib** |
| portal / ledger | boş |
| yüklənə bilən | **19 sənəd** |
| bloklanan | **18 sənəd** |
| canlı yükləmə | imza tokeni başqa şəxsdədir |

Bloklanma səbəbləri: AZF-in daxili `Q00255` / `Q01906` sənədləri (10), `AWS D1.1` (7), `ISO 11666` (1), `ISO-23278` (1). Heç biri kod qüsuru deyil — portalın siyahısı məsələsidir.

---

## 4. Mövcud config açarları

Kodda var, `settings.example.yaml`-da sənədləşib:

| açar | default | nə edir |
|---|---|---|
| `presentation.collapse_ranges` | true | ardıcıl eyni sətirləri diapazona yığır |
| `presentation.rollup_retests` | **false** | R1/R2 övladlarını gizlədir, valideyn zəncirin son verdiktini alır |
| `presentation.unfit_placement` | **inline** | `inline` \| `no_range` \| `section` \| `section_renumber` |
| `filtering.merge_duplicate_identities` | **false** | transpozisiya cütlərini birləşdirir (`MT-U-25-028` ↔ `U-MT-25-028`) |
| `filtering.collapse_standard_spaces` | true | standartda təkrarlanan boşluqları sıxır |

**Kritik:** `rollup_retests`, `unfit_placement` və `merge_duplicate_identities` **canlı `config/settings.yaml`-da yoxdur**, ona görə default (köhnə) davranış işləyir.

---

## 5. YENİ PROBLEMLƏR — hazırkı iş budur

Selim UBOC APR 2025 sənədinə baxdı və üç problem gördü.

### Problem 1 — R1/R2 sətirləri görünür
```
1   MT-U-25-028     Yarasız
1a  MT-U-25-028R1   Yararlı
1b  MT-U-25-028R2   Yararlı
```
Müdürün tələbi: `28, 29, 30` ardıcıl bir seriya kimi, R1/R2 olmadan, birbaşa son nəticə ilə.
**Səbəb:** `rollup_retests` sönülü. Kod hazırdır.

### Problem 2 — dublikat sətirlər
```
1  MT-U-25-028   İtem sütunu BOŞ
3  U-MT-25-028   İtem: C100B80X939 crane (North side)
```
Eyni yoxlama, nömrə tərs yazılıb. Boş İtem-li sətir arxiv PDF-dir, dolu olan canlı `.docx`-dir.
**Səbəb:** `merge_duplicate_identities` sönülü. Birləşmə canlı `.docx`-i saxlayır, yəni İtem adları qazanılır.

### Problem 3 — nömrə boşluğu, `030` → `033`
`031` və `032` yoxdur. **Səbəb UNKNOWN — ölçülməlidir.** Ehtimallar var (dəstəklənməyən standarta görə sətir atılıb — son run-da 379 belə sətir vardı; tarix karantini; başqa ay qrupuna düşüb), amma heç biri təsdiqlənməyib. Təxmin qadağandır.

---

## 6. Birinci prompt — bunu Claude Code-a ver

```
/caveman istifadə et.
TƏXMİN ETMƏ. BİLMƏDİYİN MƏLUMATI UYDURMA.

UBOC APR 2025 sənədində üç problem göründü. İkisi açar məsələsidir,
üçüncüsü ölçülməlidir.

0) ƏVVƏLCƏ output/ backup-ı al.

1) config/settings.yaml-a üç açarı ƏLAVƏ ET:
     presentation.rollup_retests: true
     presentation.unfit_placement: section
     filtering.merge_duplicate_identities: true
   Bunlar kodda var, sadəcə canlı config-də yoxdur.

2) 031 / 032 SIÇRAYIŞINI ARAŞDIR — bu əsas sualdır.
   UBOC APR 2025-də MT-U-25-030-dan sonra birbaşa 033 gəlir.
   Hər nömrə üçün DƏQİQ səbəb göstər:
     - input/ ağacında belə fayl varmı? (bütün variantlar:
       MT-U-25-031, U-MT-25-031, PDF_ARCHIVE, SKIPPED_REPORTS, _PRUNED)
     - varsa, niyə sənədə düşməyib? dəstəklənməyən standart?
       tarix karantini? başqa ay/müştəri qrupuna düşüb?
     - ümumiyyətlə yoxdursa, bunu açıq yaz — mənbədə yoxdur.
   Sonra eyni metodla BÜTÜN korpusda boşluqları çıxar: hər müştəri-ay
   üçün nömrə silsiləsindəki boşluqlar və hər boşluğun səbəbi.
   Nəticə: output/-dan KƏNARDA (samples/ altında), azərbaycanca hesabat.

3) Yenidən qur və UBOC APR 2025-i göstər:
   - neçə sətir qaldı (əvvəl / sonra)
   - MT-U-25-028 / U-MT-25-028 cütü birləşdimi, İtem adı qaldımı
   - R1/R2 sətirləri gizləndimi
   - nömrələr boşluqsuz gedirmi

Ölç, təxmin etmə. Bilmirsənsə UNKNOWN yaz.
DAYAN, nəticəni göstər. --live yoxdur.

Qırmızı xətlər: uploader.py refactor edilmir, hesabat nömrələri
dəyişdirilmir, print()/log mətnləri dəyişmir, davranış səssizcə dəyişmir.
```

---

## 7. Dəyişməz qərarlar (yenidən müzakirə edilmir)

1. **Zero substitution** — standart əvəz edilmir.
2. **Portal standartları = 16**, canlı probe ilə ölçülüb (`output/portal_form_probe.json`, 12.08.2026). Şirkətin 37-lik siyahısı portalın siyahısı **deyil**. Genişləndirmə **RƏDD EDİLDİ** — dry-run oracle yanlış yaşıl olardı.
3. **AZF standartları** sənəddə görünür, portala **filed olunmur**. AZF-in 21 sənədindən heç biri portala getmir.
4. **SDLN-in `GIS-42-103` və `EP-GIS-42-103`** — qəsdən kənarda.
5. **Sidecar = həqiqət mənbəyi.** PDF görünüşdür.
6. **Bütün layout `pdf_renderer.py`-dədir** (ADR-001).
7. **`uploader.py` refactor edilmir** (ADR-002) — qırmızı xətt.
8. **Sənəd başlığı: `Obyekt: <müştəri adı>`**, `Müştəri:` yox. `item_detail`-dan "obyekt" qurulmur — bir dəfə sınandı, tam yanlış idi.
9. **Metod zolağı yoxdur**, cədvəldə `Üsul` sütunu (7 sütun).
10. **Canlı `.docx` həmişə qalib gəlir**, `PDF_ARCHIVE` nüsxəsi heç vaxt.
11. **`output/` altına nümunə/sınaq faylı yazılmır** — ledger açarını çirkləndirir (`uploader.py:2098` rekursiv gəzir). Nümunələr `samples/` altındadır, `.gitignore`-dadır.

---

## 8. Qırmızı xətlər

- `uploader.py` toxunulmur
- Hesabat nömrələri **heç vaxt** dəyişdirilmir, təmizlənmir, `rej` kimi sonluqlar silinmir (`U-UT-25-003rej` real nömrədir)
- Mövcud `print()` / log mətnləri dəyişmir
- Davranış **səssizcə** dəyişmir — yeni davranış config açarı ilə gəlir
- Operatorun fayllarında ad dəyişmir, fayl silinmir
- `main.py` stage sırası dəyişmir

---

## 9. Bitmiş iş (ölçülmüş)

| iş | nəticə |
|---|---|
| B1 | 20 sənəd nömrəsi səhv aya yazılırdı → 0 |
| KB-1 / KB-1b | 247 kəsilmiş tarix; 234 bərpa, karantin 81 → 13 |
| ADR-003 | pdf2docx silindi. 96/630 səhv verdikt → 0 səssiz səhv. Run ~6.9 saat → ~40 saniyə |
| ADR-004 | qruplaşdırma `ay × metod × müştəri` → `ay × müştəri`. 278 → 103 sənəd |
| ADR-005 | duplicate_identity: 231 cüt = 215 birləşən + 14 həqiqətən ayrı + 2 qərarsız |
| A4-V2 | ingestion content-dedup |
| E3 | rollup_retests + unfit_placement |
| boşluq düzəlişi | `Q01906` iki yazılışda idi, birləşdi |

**Qeyd:** "karantin 13" KB-1-in bir dəfəlik nəticəsidir, hər run-ın gözlənilən rəqəmi **deyil**. Son run-da karantinə 0 fayl getdi.

---

## 10. Açıq blokerlər

- **`AWS D1.1`** portalda yoxdur → 7 sənəd bloklanıb. Sorğu 22.07.2026-da verilib.
- **AZF `Q00255` / `Q01906`** — müştərinin daxili sənədləridir, portalda yoxdur → 10 sənəd.
- **B2 tərcümələr** — operator `output/item_translation_review_2026-09-17.md`-də azərbaycanca sütunu doldurmalıdır. 73 termin; ən böyükləri `SDLN WORK SHOP` 436, `WQT` 188, `Pipe to flange` 55.
- **A4-V3** — `UnSorted` kilidi, profilaktik, ölçülməyib.
- **`KF-MT-26-058` / `KF-MT-26-058R1`** daimi ilişib — hər run 2 imtina, 0 fayl köçür.
- **İki qüsurlu fayl adı** — `U-RT-26-130VG).docx`, `U-RT-26-131VG).docx`, açılan mötərizə yoxdur. LAN-da düzəlməlidir.
- **14 nömrə toqquşması + 2 qərarsız** — `output/report_no_collisions_2026-09-18.md`, müfəttişə verilməlidir.
- **Canlı yükləmə** — imza tokeni gözlənilir. Birinci yoxlanacaq: portalın "Nəticə" sahəsinin real adı və qəbul etdiyi dəyərlər (kod `Yararlı` yazır, portalda belə anlayışın olub-olmaması **təsdiqlənməyib**).
- **UNKNOWN** — ikiblokdlu sənədi (əsas cədvəl + "Təkrar yoxlanılmamış yararsız qaynaqlar" bölməsi) portal və müfəttiş qəbul edirmi. `samples/e3/` altındakı iki nümunə PDF məhz bunu yoxlamaq üçündür.

---

## 11. Faydalı əmrlər

```
python -m pytest -q
python main.py --force-rebuild
python uploader.py --dry-run --all --limit 200
python uploader.py --help
```

Canlı yükləmə (**hələ YOX**): `python uploader.py --live --interactive --limit 2`

---

## 12. Bu chatın ilk cavabı

Yalnız təsdiqlə: rolu, hazırkı üç problemi, qırmızı xətləri. Yeni iş başlatma. Selimin gətirəcəyi nəticəni gözlə.
