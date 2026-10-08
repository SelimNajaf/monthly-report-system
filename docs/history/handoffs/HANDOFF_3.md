# HANDOFF əlavəsi — 18.09.2026

`HANDOFF_2.md` ilə birlikdə oxunur. Onun 8-ci bölməsindəki növbə **bağlanıb**.

## E3 tamamlandı

Yeni config açarları (`presentation:` bloku):

| açar | default | dəyərlər |
|---|---|---|
| `rollup_retests` | `false` | retest övladları gizlənir, valideyn zəncirin son verdiktini alır |
| `unfit_placement` | `inline` | `inline` \| `no_range` \| `section` \| `section_renumber` |

Seçilən rejim: **`section`** (V3 — ayrıca bölmə, nömrələmə davam edir).
Bölmə başlığı: **"Təkrar yoxlanılmamış yararsız qaynaqlar"** (`az.json`-a yeni açar).

Dəyişən fayllar: `document_aggregator.py` (`split_display_rows`), `pdf_renderer.py` (ikinci blok, layout yalnız burada), `az.json`, `settings.example.yaml`, `tests/test_unfit_section.py` (16 test).

**1729 test keçir, 14 skip. Commit edilməyib.**

## Düzəlmiş rəqəm

Təmir olunmamış rədd **157 deyil, 158**. LAN-dan gələn 21 yeni hesabatdan biri də rəddir. Müdürə 158 deyilməlidir.

Bölgü (18.09 ölçməsi): rədd→təmir→Yararlı **54**, rədd→təkrar da rədd **0**, rədd→təkrar yoxlanmayıb **158**, keçib amma retesti var **40**.

## Nümunə PDF-lər — `samples/e3/`

| | AZF JAN 2026 | UBOC APR 2026 |
|---|---|---|
| sidecar sətri | 49 | 37 |
| əsas cədvəl | 26 | 5 |
| ayrıca bölmə | 10 | 1 |
| son Sıra № | 36 | 6 |
| gizlənən retest övladı | 0 | 18 |

AZF-də retest yoxdur — yalnız ayrıca bölməni göstərir. UBOC hər iki açarı göstərir.

**Müdürə mütləq deyiləsi:** UBOC nümunəsində 10 Yarasız sətirdən **9-u sənəddə heç yerdə görünmür** — hamısı Yararlı diapazonların içinə düşür, yalnız sidecar-da qalır. Bu, istənilən davranışdır, amma rəsmi sənəddə nəyin itdiyi bilinməlidir.

Konkret nümunə: `12 U-RT-26-012 Yarasız` + `12a U-RT-26-012R1 Yararlı` → `4 U-RT-26-(012-017) Yararlı`.

**UNKNOWN / NEEDS VERIFICATION:** ikiblokdlu sənədi portal və dövlət müfəttişi qəbul edirmi. Nümunə məhz bunu yoxlamaq üçündür.

## Ledger qaydası (yeni)

`output/` altına nümunə/sınaq faylı yazmaq **ledger açarını çirkləndirir** — `uploader.py:2098` `output/`-u rekursiv gəzir, `upload_ledger.ledger_key` açarı yola görə qurur, yəni eyni sənəd iki ayrı açar alır və iki dəfə yüklənə bilər. Nümunələr `samples/` altında saxlanılır, `samples/` `.gitignore`-dadır.

## Növbəti iş — yükləmə testi, CANLI DEYİL

1. Hansı sənədlərin **bütün** standartları portalın 16-lıq siyahısındadır — ölç və sadala. Yalnız onlar yüklənə bilər.
2. Onlardan biri üçün dry-run: formanın hər sahəsinə nə yazılacağını göstər (VÖEN, müştəri, standart(lar), tarix, nəticə sahəsi, əlavə olunan PDF).
3. **Portalın "Nəticə" sahəsi** — kod `Yararlı` yazır, portalda belə anlayışın olub-olmaması təsdiqlənməyib. Real sahə adı və qəbul etdiyi dəyərlər göstərilsin; bilinmirsə `UNKNOWN`, təxmin yox.
4. Standartların siyahısının genişləndirilməsi **sonraya qalır**. Zero substitution qüvvədədir.
5. `--live` yoxdur, e-imza klikləmir, imza tokeni hələ başqa şəxsdədir.

## Selimin öz tərəfində qalanlar

- Commit qərarı (bütün dəyişikliklər commit edilməyib)
- Müdürə: 158 rəqəmi + 2 nümunə PDF + UBOC-dakı 9 itən Yarasız
- Müfəttişə: `output/report_no_collisions_2026-09-18.md`
- LAN-da iki fayl adı: `U-RT-26-130VG).docx`, `U-RT-26-131VG).docx` — açılan mötərizə yoxdur
- Operatora: `output/item_translation_review_2026-09-17.md` azərbaycanca sütunu (B2)
