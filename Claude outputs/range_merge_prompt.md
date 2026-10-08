/caveman skillindən istifadə et.
TƏXMİN ETMƏ. BİLMƏDİYİN MƏLUMATI UYDURMA.
Bilinməyəni "UNKNOWN / NEEDS VERIFICATION" kimi qeyd et.

# Tapşırıq: by_number diapazonlarını genişləndirmək (etiket, standart, İtem)

Kontekst: ADR-009. Nümunə sənəd `output/KHF/compiled_monthly_report_KHF_JUN_2026.*`. Bu sənəddə 23 sətir var və heç biri birləşmir. Səbəblər:

- hər hesabatın öz etiketi var: `(2236)`, `(2274)`…
- standart növbə ilə dəyişir;
- İtem standartla birlikdə dəyişir.

## Selimin qərarları

- **E1.** Etiket (mötərizədəki hissə) diapazonu qırmır. Diapazon sətri etiketsiz çap olunur: `KF-MT-26-(039-051)`. Tək nömrəli sətir öz adını olduğu kimi saxlayır: `KF-MT-26-054 (2334)`.
- **E2.** Fərqli standart diapazonu qırmır. Standart xanasında diapazondakı fərqli standartların hamısı yazılır, vergül ilə, ilk görünmə sırasına görə (nömrə sırası ilə). Nümunə: `AWS D1.1, EEMUA 158, ASME B31.3`. Təkrar yazılmır.
- **E3.** Fərqli İtem diapazonu qırmır. İtem xanasında **yalnız bir** dəyər yazılır: diapazonda ən çox rast gəlinən İtem (nömrə vahidləri üzrə sayılır). Bərabərlik olsa, ən kiçik nömrənin İtem-i götürülür. Boş İtem sayılmır; hamısı boşdursa, xana boş qalır.
- **Dəyişməyənlər:**
  - Diapazonu hələ də bunlar qırır: nömrə boşluğu, prefiks, üsul, sıfır genişliyi, `range_tail_allow` qaydası.
  - Nəticə qaydası, `[range-verdict]` və audit md dəyişmir.
  - Vahid daxilində (valideyn və retest) fərqli standart/İtem varsa, E2/E3 aktiv olanda vahid bu səbəbdən bölünmür. Dəyərlər vahid üçün də eyni qayda ilə seçilir.

## Config

Yalnız `range_mode: by_number` altında işləyir. Default köhnə davranışdır, açarlar söndürülübsə çıxış byte-identik qalır.

| Açar | Default | Yeni dəyər |
|---|---|---|
| `presentation.range_ignore_tag` | `false` | `true` → E1 |
| `presentation.range_merge_standards` | `false` | `true` → E2 |
| `presentation.range_item` | `split` | `dominant` → E3 |

- `split` bugünkü davranışdır, yəni `split_ranges_on_item` ilə idarə olunur.
- `dominant` aktiv olanda `split_ranges_on_item` by_number-də nəzərə alınmır.
- Daha yaxşı ad və ya struktur təklifin varsa, əsaslandır.

## Gözlənti (KHF_JUN_2026, sidecar-dan yoxla, fərq varsa izah et)

| # | Report № | Tarix | Standart | İtem | Nəticə |
|---|---|---|---|---|---|
| 1 | MT `KF-MT-26-(039-051)` | 09–29.06.2026 | AWS D1.1, EEMUA 158, ASME B31.3 | Konstruktiv tikiş | Yararlı |
| 2 | MT `KF-MT-26-054 (2334)` | 22.06.2026 | ASME B31.3 | Boru kəməri | Yararlı |
| 3 | UT `KF-UT-26-(010-017)` | 12–29.06.2026 | EEMUA 158, ASME B31.3, AWS D1.1 | Konstruktiv tikişlər | Yararlı |
| 4 | HrT `KF-HrT-26-005 (2152)` | 01.06.2026 | ASME B31.3 | Boru kəməri | Məlumat üçün |

- MT-də 052 və 053 yoxdur. 054 ayrıca sətir olur.
- İtem sayları mənim hesabımdır: MT-də "Konstruktiv tikiş" 8, "Boru kəməri" 4; UT-də "Konstruktiv tikişlər" 3. Yoxla.

## Mütləq yoxla və yaz

1. Uploader standartları yalnız sidecar-dan oxuyur, PDF-dən oxumur. Bunu fayl:sətir ilə göstər. Sidecar byte-identik qalmalıdır. Qalmırsa, BLOKLAYAN SUAL.
2. Standart xanası uzananda sətir hündürlüyü artır. Bir-iki nümunədə ölç.
3. Sonra sətir sayları ölçüləcək. İndi yalnız UNKNOWN kimi qeyd et.

## Addımlar

1. **Plan:** fayl, funksiya, sətir; açarların qarşılıqlı təsiri; sınacaq testlər; BLOKLAYAN SUALLAR. Bloklayan sual varsa, burada DAYAN.
2. **Kod.**
3. **Testlər:**
   - defaultlar byte-identik;
   - E1: etiket fərqi birləşir, tək sətir etiketini saxlayır;
   - E2: standart siyahısı, sıra, təkrar yoxdur;
   - E3: çoxluq, bərabərlik, boş İtem;
   - boşluq hələ qırır;
   - vahid daxilində fərq;
   - KHF_JUN_2026 gözləntisi fixture ilə.
4. `settings.example.yaml`-a şərhlər əlavə et. Canlı `settings.yaml`-a toxunma.
5. `python -m pytest -q` (əvvəl 1886/14/0). Nəticəni yaz.

Sonra DAYAN. `main.py` işlətmə, commit etmə.

## Qırmızı xətlər

- `uploader.py`-a toxunma.
- Hesabat nömrələri dəyişmir. Etiket sidecar-dan silinmir, yalnız PDF diapazon sətrində göstərilmir.
- Mövcud `print()` mətnləri dəyişmir.
- Layout yalnız `pdf_renderer.py`-dədir.
- `output/`-a yazma.
- `--live` yoxdur.
