/caveman skillindən istifadə et.
TƏXMİN ETMƏ. BİLMƏDİYİN MƏLUMATI UYDURMA.
Bilinməyəni "UNKNOWN / NEEDS VERIFICATION" kimi qeyd et.

# Tapşırıq: ADR-006, 007, 008, 009 yazmaq (yalnız sənəd, kod dəyişmir)

`architecture/`-da yalnız ADR-001–005 var. 006–008 əvvəlki sessiyada yazılmalı idi, amma yoxdur. 009 bu sessiyanın dəyişikliyidir.

## Mənbələr (yalnız bunlardan yaz)

- Mövcud ADR-001–005 — format, başlıq strukturu və dil üçün nümunə. Eyni şablonu işlət.
- `config/settings.example.yaml` — açarların şərhlərində ölçülmüş rəqəmlər var.
- Kod: `document_aggregator.py`, `retest_tracker.py`, `report_no_mismatch.py`, `pdf_renderer.py`, `json_exporter.py`, `main.py`.
- Testlər: `test_pulled_parent_mark.py`, `test_pull_weld_check.py`, `test_report_no_mismatch.py`, `test_range_by_number.py`, `test_range_tail_and_dates.py`.
- `output/` altındakı audit md faylları (`report_no_mismatch_*`, `report_no_collisions_2026-09-18.md`, `range_verdict_*`) — yalnız oxu.
- Commit-lər: `9d54e26`, `fae8fdc` (git show).

Hər rəqəmi mənbə ilə yoxla. Mənbəsi tapılmayan rəqəmi yazma və ya UNKNOWN qeyd et.

## ADR-006 — Gətirilmiş valideyn sətri: arayış, bəyan deyil

- Kontekst: retest başqa ayın valideynini gətirir; o sətir öz ayının sənədinə aiddir.
- Qərar: `pulled_parent_style` — `plain` (default) | `marked` (`*` + qeyd + sidecar-da `pulled_from`) | `hidden` (ADR-009, PDF-də görünmür; sidecar `marked` ilə byte-identik).
- Rəqəmlər: gətirilmiş sətirlərin sayı, sənəd sayı. Mənbədə 31 və 30 var (strict bir sətri rədd edir) — hər ikisini mənbəsi ilə izah et.

## ADR-007 — Pull tikiş sübutu ilə qorunur

- `retest.pull_weld_check: off | strict`. Qaydalar settings.example.yaml şərhindən.
- Rəqəmlər: 21 tikişlə, 9 ikinci dərəcəli sübutla, 1 rədd (`U-RT-26-005`, QB-4 ≠ QB-5) — kodla və ya auditlə təsdiqlə.
- Səbəb: nömrə iki işə verilə bilir, fayl başqa hesabatın məzmununu daşıya bilir.

## ADR-008 — Fayl adı ≠ içəridəki nömrə

- Hər run-da xəbərdarlıq (stdout + `report_no_mismatch_<tarix>.md`). Heç vaxt ad dəyişmir və nömrə düzəldilmir.
- `filtering.block_mismatched_report_no` (default false): yalnız tam surəti sənəddən çıxarır.
- Rəqəmlər: 22 fayl, 9 surət — auditdən təsdiqlə.

## ADR-009 — Nömrəyə görə diapazon, sadə cədvəl

Kontekst: müdirin tələbi — sənəd sadə və qısa olsun. Əvvəlki görünüşdə tarixlər qarışıq idi (Mart valideynləri aprel sənədində), 2a/2b sətirləri, sarı fon və ikinci cədvəl vardı.

Qərar (Selimin qərarları D1–D8 + Q1–Q6):

- `range_mode: by_number` — retest suffiksi nəzərə alınmır, nəticə birləşməyə mane olmur. Qırılma halları: boşluq, prefiks, üsul, standart, İtem, etiket, sıfır genişliyi.
- Tarix: min–max; `01–21.04.2026` / `31.03–15.04.2026` / `28.12.2025–05.01.2026`. Tarix sütunu 27 mm (yalnız by_number).
- Nəticə: diapazonda ən azı bir nömrə Yararlı bitibsə "Yararlı", heç biri deyilsə "Yarasız". Tək nömrə öz zəncirinin son nəticəsini göstərir. Info metodları "Məlumat üçün".
- İkinci cədvəl yoxdur. `pulled_parent_style: hidden`.
- `row_order: method_volume` (default `method_date`). `row_style: method_zebra` (default `retest_highlight`).
- `range_tail_allow` (default `[]`; canlıda `["T"]`). `rej`, `test`, `del` heç vaxt birləşmir.
- Açarların qarşılıqlı təsiri: `collapse_ranges: false` by_number-i üstələyir; rollup və unfit_placement by_number-də nəzərə alınmır; hidden+strict marked kimi oxunur.

Səbəb (Selimin sözü ilə): portal sənədin ümumi nəticəsinə baxır. Sidecar dəyişmir, həqiqət mənbəyi qalır.

**Risk (açıq yaz, yumşaltma):** PDF-də son nəticəsi Yarasız olan hesabatlar Yararlı diapazon sətri altında çap olunur. İnspektor bu PDF-ə imza atır. Ölçülən rəqəm: 95 hesabat (82 + T diapazonlarından 13). Sənəd sayını `range_verdict_*.md`-dən say. Azaldıcı tədbir: `[range-verdict]` stdout sətri + `output/range_verdict_<tarix>.md` auditi. Qərar operatorundur.

Ölçülər: 127 sənəd üçün sətir 1787 → 1479, səhifə 151 → 141, sidecar fərqi 0, test 1886/14/0. Hər birini mənbədə yoxla. Yoxlanmayanı UNKNOWN kimi qeyd et.

## Qaydalar

- Yalnız `architecture/ADR-006-*.md` … `ADR-009-*.md` yarat. Adlar mövcud ADR-lərin şablonunda olsun.
- README və ya başqa sənəddə ADR indeksi varsa, oraya da əlavə et; yoxdursa, yaratma.
- Real VÖEN, FİN, adlar və LAN yolları yazılmır.
- Kod dəyişmir, `output/`-a yazılmır, `uploader.py`-a toxunulmur.
- Sonra: `python -m pytest -q` (1886/14/0). Commit mesajı: `docs(adr): ADR-006..009 — pulled parent, weld check, report-no mismatch, by-number ranges`. Push etmə.
- Hər ADR-də UNKNOWN qalan yerlərin siyahısını ver. Sonra DAYAN.
