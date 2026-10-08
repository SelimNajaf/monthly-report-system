/caveman skillindən istifadə et.
TƏXMİN ETMƏ. BİLMƏDİYİN MƏLUMATI UYDURMA.
Bilinməyəni "UNKNOWN / NEEDS VERIFICATION" kimi qeyd et.

# P1 — ADR-003 verdikt qapısının bərpası

**Vəziyyət** (`docs/CODE_MAP_2026-09-28.md` §2.9): `tests/test_verdict_regression.py`-dəki 14 test həmişə skip olunur. Səbəb: 630 hesabatlıq manifestdən 20-si `input/PDF_ARCHIVE/`-də yoxdur, 2026-09-07-də `input/SKIPPED_REPORTS/`-ə düşüb. Onların 7-si testin qorumaq üçün yazıldığı RT hallarıdır.

**Seçilən yol:** CODE_MAP-dəki variant 1 + variant 3.

## Addım 1 — Plan (kod yazmadan). DAYAN, təsdiq gözlə.

1. Test manifestin hansı sahələrini işlədir? Hər hesabatı necə tapır?
   - Manifestdə fayl hash-i (sha256) varmı? Yoxdursa, korpusun doğru fayllardan qurulduğunu necə sübut edəcəyik?
2. Çatışmayan 20 hesabat üçün cədvəl: report №, `SKIPPED_REPORTS`-dakı namizəd fayl(lar), sha256, uyğunluq sübutu.
   - `PDF_ARCHIVE`-də eyni açara düşən təkrarlar var (791 PDF 785 açara düşür). Belə hallarda testin hansını seçdiyini göstər. Təxmin etmə.
3. **Korpus dizaynı:**
   - Yeni qovluq `corpus/verdict_regression/` (gitignored). 630 PDF buraya **kopyalanır**. `input/` oxunur, amma dəyişmir.
   - Kopyalanan hər faylın sha256-sı `corpus/verdict_regression/MANIFEST.sha256`-ya yazılır. Bu fayl da gitignored-dir.
   - Test korpusu belə tapır: env var `MRS_VERDICT_CORPUS`, yoxdursa default `corpus/verdict_regression/`.
4. **Skip qaydası (variant 3):**
   - Korpus qovluğu yoxdursa → skip, amma səbəb açıq yazılsın: "verdict gate NOT RUNNING: corpus missing — see TODO P1". `pytest -rs`-də görünməlidir.
   - Korpus var, amma natamamdır və ya hash uyğun gəlmir → **FAIL**, çatışmayan və ya uyğunsuz faylların siyahısı ilə.
   - Korpus tamdır → testlər həqiqətən işləyir.
5. Korpusu qurmaq üçün skript: `scripts/build_verdict_corpus.py`.
   - İdempotent olsun. Yalnız `input/`-dan oxusun. Heç vaxt köçürməsin və silməsin.
   - Yalnız hədəf qovluğa yazsın. `--dry-run` rejimi olsun.
6. Hansı mövcud testlər dəyişir, hansı yeni testlər əlavə olunur?

## Addım 2 — Kod (yalnız "davam"dan sonra)

1. Skript, test dəyişikliyi və `.gitignore`-a `corpus/` sətri (CRLF saxla).
2. Əvvəl `--dry-run`, sonra real qurma. Korpusdakı fayl sayı və ümumi ölçü.
3. `python -m pytest -q tests/test_verdict_regression.py -rs`. Nəticəni tam yaz.
   - **Qapı qırmızı çıxsa:**
     - kodu düzəltməyə çalışma;
     - testi yumşaltma;
     - hansı hesabatın hansı yoxlamadan keçmədiyini (`silent`, karantin dəsti, adlı hallar) yaz və DAYAN.
     - Bu, real tapıntıdır. Qapı 4570af1-dən bəri işləməyib, bu müddətdə presentation dəyişiklikləri edilib.
4. Tam suite: `python -m pytest -q`.
5. `docs/INDEX.md`-yə `corpus/` və skript üçün sətir əlavə et. `test_index_sync` yaşıl olmalıdır.
6. `CLAUDE.md`-də dəyişikliklər:
   - §8-dəki verdikt tələsini yeni vəziyyətə uyğun yenilə;
   - §9-a qeyd əlavə et: "(Git Bash — PowerShell-də `tail`/`wc`/`grep` yoxdur)".
7. `TODO.md` P1: qapı yaşıldırsa, bağla və jurnala sübut yaz; qırmızıdırsa, açıq qalsın və tapıntını əlavə et.
8. Commit: `test: restore ADR-003 verdict gate with a pinned corpus`. Push etmə. DAYAN.

## Qırmızı xətlər

- `input/`-da heç nə köçürülmür, silinmir və ya adı dəyişmir.
- `corpus/` və içindəki PDF-lər git-ə düşmür.
- Verdikt məntiqi (`pdf_reader`, `pdf_crosscheck`, `docx_reader`) dəyişmir. Test qırmızı olsa, kod yox, tapıntı yazılır.
- `tests/data/verdict_regression.json`-dakı gözləntilər dəyişmir.
- `uploader.py`-a toxunulmur, `--live` yoxdur.
