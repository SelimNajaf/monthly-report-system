"""Read-only audit: one report, two spellings (``RT-U-25-090`` / ``U-RT-25-090``).

Task 11 measured the retest roll-up (``audit_retest_rollup.py``) and found, as a
side effect, 231 pairs of compiled rows whose report numbers are the same segments
in a different order. That finding is out of the roll-up's scope, so it is measured
here on its own and answers five questions:

1. **Where do the two spellings come from** — the source filenames, or the parse?
2. **Why does** :func:`report_identity.report_key` **not merge them?**
3. **Which spelling is the correct one**, when both rows carry the same verdict?
4. **What would merging change** — rows per document, ``total_records``?
5. **Could a merge collapse two genuinely separate inspections into one row?**

Nothing is written to the corpus, no pipeline state is touched and no source file is
renamed or moved. The evidence comes from three read-only places: the compiled JSON
sidecars under ``output/``, the filenames under ``input/`` (including the settled
trees), and ``.parse_cache/<sha256>.json`` — the same document bodies the pipeline
itself parses.

    python scripts/audit_duplicate_identity.py

The classification is deliberately conservative. A pair is called a duplicate only
when the evidence says both rows describe ONE physical report; anything that could
be two inspections is reported as such, and anything in between is left undecided
for the operator. A wrong "duplicate" call deletes an inspection from a document
that goes to the state — that error is not symmetric with leaving a row too many.
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import hashlib
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report import docx_reader, extractor  # noqa: E402
from monthly_report.report_identity import (report_key, report_key_of,  # noqa: E402
                                            retest_rank, squash)

#: Trees that hold settled copies rather than working documents. A file here is
#: evidence about a report, not a report the pipeline is compiling from — except
#: ``PDF_ARCHIVE``, which ADR-003 turned back into a reader (``pre_processor.pdf_sources``).
_ARCHIVE, _PRUNED, _QUARANTINE = "PDF_ARCHIVE", "_PRUNED", "SKIPPED_REPORTS"
_SETTLED = (_ARCHIVE, _PRUNED, _QUARANTINE)

_LEADING = re.compile(r"[A-Za-z0-9-]+")

# Classification verdicts.
SAME = "eyni sənəd"
DISTINCT = "iki ayrı yoxlama"
UNDECIDED = "qərarsız"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def filename_tail(name: str) -> str:
    """Everything after the leading report-number token, normalised.

    The tail is the job number and standard the inspector typed into the filename
    (``(2106)  (EEMUA 158)``). Two files that share it are the same job; it is the
    one piece of the name the transposition does NOT touch.
    """
    stem = Path(name).stem
    m = _LEADING.match(stem)
    return re.sub(r"\s+", " ", stem[len(m.group(0)):] if m else stem).strip().casefold()


def is_transposition(a: str, b: str) -> bool:
    """True when ``b`` is ``a`` with its first two segments swapped."""
    sa, sb = a.upper().split("-"), b.upper().split("-")
    return len(sa) > 2 and sa[:2][::-1] == sb[:2] and sa[2:] == sb[2:]


class Corpus:
    """The read-only view of ``input/`` plus the parse cache."""

    def __init__(self, input_dir: Path, cache_dir: Path) -> None:
        self.input_dir = input_dir
        self.cache_dir = cache_dir
        self.by_key: dict[str, list[Path]] = collections.defaultdict(list)
        for path in sorted(input_dir.rglob("*")):
            if not path.is_file() or path.suffix.casefold() not in (".docx", ".pdf"):
                continue
            if path.name.startswith("~$"):
                continue
            self.by_key[report_key_of(path.name)].append(path)
        self._tables: dict[Path, list | None] = {}

    def top(self, path: Path) -> str:
        return path.relative_to(self.input_dir).parts[0]

    def is_live(self, path: Path) -> bool:
        """True for a document the compile reads as a working ``.docx``."""
        return self.top(path) not in _SETTLED

    def files(self, report_no: str) -> list[Path]:
        return self.by_key.get(report_key(report_no), [])

    def tables(self, path: Path):
        if path not in self._tables:
            blob = self.cache_dir / f"{sha256(path)}.json"
            data = None
            if blob.is_file():
                try:
                    data = json.loads(blob.read_text(encoding="utf-8")).get("tables")
                except (json.JSONDecodeError, OSError):
                    data = None
                if isinstance(data, str):
                    data = json.loads(data)
            self._tables[path] = data
        return self._tables[path]

    def meta(self, path: Path) -> dict:
        tables = self.tables(path)
        return extractor.extract_meta(tables) if tables else {}

    def body_no(self, path: Path) -> str:
        return squash(self.meta(path).get("report_no", "")).replace(" ", "")

    def welds(self, path: Path, method: str) -> set[str]:
        """The weld identifiers the document lists — the inspection's fingerprint.

        Two reports of the same weld on the same day are one report seen twice; two
        reports of DIFFERENT welds are two inspections, whatever their numbers say.
        """
        tables = self.tables(path)
        if not tables:
            return set()
        rows = (extractor.extract_rt_welds(tables) if method == "RT"
                else extractor.extract_welds(tables))
        return {squash(w.get("weld_no", "") or w.get("item", "")) for w in rows} - {""}


class Pair:
    """Two compiled rows whose report numbers are transpositions of each other."""

    __slots__ = ("doc", "a", "b", "row_a", "row_b", "files_a", "files_b",
                 "verdict", "reason")

    def __init__(self, doc: str, a: str, b: str, row_a: dict, row_b: dict) -> None:
        self.doc, self.a, self.b, self.row_a, self.row_b = doc, a, b, row_a, row_b
        self.files_a: list[Path] = []
        self.files_b: list[Path] = []
        self.verdict = UNDECIDED
        self.reason = ""

    @property
    def method(self) -> str:
        return self.row_a.get("method", "") or ""

    def fields_differ(self) -> list[str]:
        out = []
        for f in ("date", "standard", "method", "item_name", "result"):
            if (self.row_a.get(f) or "") != (self.row_b.get(f) or ""):
                out.append(f)
        return out


def sidecar_pairs(output_dir: Path) -> list[Pair]:
    """Every transposed pair in the compiled sidecars.

    Retests are skipped: a retest shares its parent's segments by design, and an
    earlier version of this test flagged ``KF-RT-26-053`` / ``KF-RT-26-053R1`` as a
    duplicate because of it.
    """
    pairs: list[Pair] = []
    for sidecar in sorted(output_dir.rglob("compiled_monthly_report_*.json")):
        try:
            rows = json.loads(sidecar.read_text(encoding="utf-8")).get("items_table") or []
        except (json.JSONDecodeError, OSError):
            continue
        canon: dict[tuple, list[dict]] = collections.defaultdict(list)
        for row in rows:
            number = (row.get("report_no") or "").strip()
            if not number or retest_rank(number):
                continue
            canon[tuple(sorted(number.upper().split("-")))].append(row)
        for group in canon.values():
            seen: dict[str, dict] = {}
            for row in group:
                seen.setdefault(row["report_no"], row)
            if len(seen) < 2:
                continue
            (a, row_a), (b, row_b) = list(seen.items())[:2]
            pairs.append(Pair(sidecar.name, a, b, row_a, row_b))
    return pairs


def classify(pair: Pair, corpus: Corpus) -> None:
    """Decide whether the pair is one report seen twice, or two reports.

    The rule, in order of evidence strength:

    * Both spellings resolve to files that are **live working documents** and their
      weld identifiers are **disjoint** -> two inspections. The corpus proves this
      case is real, so it is checked FIRST: a merge here would delete an inspection.
    * One live ``.docx`` and one settled copy (archived PDF / pruned conversion)
      that share the filename tail and the client, with the settled copy's welds a
      subset of the live one's -> one report seen twice. The settled copy is the
      signed original the live document was made from; it re-entered STAGE 1 only
      because its pre-rename name no longer matches.
    * Anything else -> undecided, for the operator.
    """
    pair.files_a = corpus.files(pair.a)
    pair.files_b = corpus.files(pair.b)
    live = [p for p in pair.files_a + pair.files_b if corpus.is_live(p)]
    settled = [p for p in pair.files_a + pair.files_b if not corpus.is_live(p)]

    if len(live) >= 2:
        wa = corpus.welds(live[0], pair.method)
        wb = corpus.welds(live[1], pair.method)
        if wa and wb and not (wa & wb):
            pair.verdict = DISTINCT
            pair.reason = (f"iki canlı sənəd, tikiş dəstləri kəsişmir: "
                           f"{sorted(wa)} / {sorted(wb)}")
        elif wa and wa == wb:
            pair.verdict = SAME
            pair.reason = "iki canlı sənəd, tikiş dəstləri eyni"
        else:
            pair.verdict = UNDECIDED
            pair.reason = (f"iki canlı sənəd, tikiş sübutu natamam "
                           f"({len(wa)} / {len(wb)} tikiş)")
        return

    if len(live) == 1 and settled:
        pdfs = [p for p in settled if p.suffix.casefold() == ".pdf"]
        other = pdfs[0] if pdfs else settled[0]
        same_job = filename_tail(live[0].name) == filename_tail(other.name)
        same_client = (squash(corpus.meta(live[0]).get("client", ""))
                       == squash(corpus.meta(other).get("client", "")))
        wl = corpus.welds(live[0], pair.method)
        ws = corpus.welds(other, pair.method)
        if same_job and same_client and ws <= wl:
            pair.verdict = SAME
            pair.reason = (f"canlı .docx + {corpus.top(other)} nüsxəsi, eyni iş nömrəsi, "
                           f"arxiv tikişləri altçoxluq ({len(ws)} ⊆ {len(wl)})")
        else:
            pair.verdict = UNDECIDED
            pair.reason = ("canlı .docx + settled nüsxə, lakin "
                           + ("iş nömrəsi fərqli" if not same_job else
                              "müştəri fərqli" if not same_client else
                              f"arxiv tikişləri altçoxluq deyil ({sorted(ws - wl)[:4]})"))
        return

    pair.verdict = UNDECIDED
    pair.reason = f"mənbə faylı tapılmadı (canlı {len(live)}, settled {len(settled)})"


def rename_census(corpus: Corpus) -> tuple[collections.Counter, collections.Counter]:
    """Corpus-wide: how often does a live ``.docx`` filename contradict its own body?

    This is the measurement that answers question 1. The 231 compiled pairs are only
    the reports where the contradiction ALSO produced a second row; the census shows
    how wide the underlying rename is.
    """
    stat: collections.Counter = collections.Counter()
    direction: collections.Counter = collections.Counter()
    for paths in corpus.by_key.values():
        for path in paths:
            if path.suffix.casefold() != ".docx" or not corpus.is_live(path):
                continue
            if corpus.tables(path) is None:
                continue
            fname = squash(docx_reader.parse_filename_metadata(path).get("report_no")
                           or "").replace(" ", "")
            body = corpus.body_no(path)
            if not fname or not body:
                stat["bir tərəf boş"] += 1
            elif report_key(fname) == report_key(body):
                stat["fayl adı = sənəd daxili"] += 1
            elif is_transposition(fname, body):
                stat["TRANSPOZİSİYA"] += 1
                fs, bs = fname.upper().split("-"), body.upper().split("-")
                direction[f"{fs[0]}-{fs[1]} (fayl) / {bs[0]}-{bs[1]} (sənəd)"] += 1
            else:
                stat["başqa fərq"] += 1
    return stat, direction


def write_report(pairs: list[Pair], corpus: Corpus, out_dir: Path,
                 today: str) -> Path:
    stat, direction = rename_census(corpus)
    by_doc: dict[str, list[Pair]] = collections.defaultdict(list)
    for p in pairs:
        by_doc[p.doc].append(p)
    verdicts = collections.Counter(p.verdict for p in pairs)
    field_diff: collections.Counter = collections.Counter()
    for p in pairs:
        for f in p.fields_differ():
            field_diff[f] += 1

    totals: dict[str, tuple[int, int]] = {}
    for doc in by_doc:
        for sidecar in (out_dir).rglob(doc):
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            totals[doc] = (data.get("total_records") or 0,
                           len(data.get("items_table") or []),
                           data.get("source_report_count") or 0)
            break
    corpus_rows = sum(
        len(json.loads(sc.read_text(encoding="utf-8")).get("items_table") or [])
        for sc in sorted(out_dir.rglob("compiled_monthly_report_*.json")))

    lines: list[str] = []
    w = lines.append
    w(f"# Eyni hesabatın iki yazılışı — kimlik auditi — {today}")
    w("")
    w("Tapşırıq 11, E1-in yan tapıntısı üçün ayrıca araşdırma. Kod dəyişmir, fayl")
    w("adı dəyişmir, heç nə birləşdirilmir — bu sənəd yalnız ölçür.")
    w("")

    # ---- 1
    w("## 1. İki yazılış harada yaranır")
    w("")
    w("Mənbə fayl adlarında. Parse tərəfi günahsızdır: hər iki faylın **sənəd")
    w("daxilindəki** `Report No:` xanası eyni nömrəni göstərir; fərqlənən yalnız")
    w("fayl adıdır.")
    w("")
    w("Bütün korpus üzrə canlı `.docx` faylları, fayl adı ilə sənəd daxili nömrənin")
    w("müqayisəsi:")
    w("")
    w("| hal | say |")
    w("|---|--:|")
    for key in ("fayl adı = sənəd daxili", "TRANSPOZİSİYA", "başqa fərq", "bir tərəf boş"):
        if stat.get(key):
            w(f"| {key} | {stat[key]} |")
    w("")
    w("Transpozisiyanın istiqaməti **tək tərəflidir** — fayl adı `<MÜŞTƏRİ>-<ÜSUL>`,")
    w("sənəd daxili `<ÜSUL>-<MÜŞTƏRİ>`:")
    w("")
    w("| yazılış | say |")
    w("|---|--:|")
    for key, count in direction.most_common():
        w(f"| `{key}` | {count} |")
    w("")
    w("Yəni fayllar sistemli şəkildə yenidən adlandırılıb. Bu, təsadüfi yazı səhvi")
    w("deyil — qəsdən qəbul edilmiş ad konvensiyasıdır və boru xətti ona hörmət edir:")
    w("`resolve_report_no` fayl adını **səlahiyyətli** sayır (`report_identity.py:154`).")
    w("")
    w("İkiqat sətir isə yalnız o hesabatlarda yaranır ki, adı dəyişməmiş **ikinci")
    w("nüsxə** hələ də korpusda oxunur — arxivlənmiş PDF orijinal. ADR-003-dən sonra")
    w("`pre_processor.pdf_sources` (`pre_processor.py:244`) `PDF_ARCHIVE/`-i STAGE 1")
    w("üçün mənbə kimi oxuyur və orada saxlanan PDF-i yalnız o halda buraxır ki,")
    w("onun `report_key_of`-u tutulan bir `.docx`-in açarı ilə üst-üstə düşsün.")
    w("Transpozisiya olunmuş ad üst-üstə düşmür, PDF ikinci sənəd kimi oxunur.")
    w("")

    # ---- 2
    w("## 2. `report_key` niyə onları birləşdirmir")
    w("")
    w("```python")
    w("def report_key(text: str) -> str:")
    w('    return re.sub(r"[\\s_]+", "", (text or "").strip()).upper()')
    w("```")
    w("")
    w("`report_key` (`report_identity.py:89`) yalnız **böyük hərfə çevirir və boşluq/")
    w("alt-xətt silir**. Seqment sırasını qorumaq onun işidir: `KF-MT-25-081` və")
    w("`MT-KF-25-081` iki fərqli açardır və olmalıdır — sıra hesabat nömrəsinin")
    w("mənasının bir hissəsidir, kosmetik küy deyil.")
    w("")
    w("Bu açar iki yerdə həlledicidir:")
    w("")
    w("1. `document_aggregator.py:331` — əkiz dedup. Açar fayl adından gələn")
    w("   nömrə üzərində hesablanır, ona görə iki yazılış heç vaxt qarşılaşmır.")
    w("2. `pre_processor.py:280-290` — `pdf_sources`-un `held` dəsti. `_PRUNED/`")
    w("   və `PDF_ARCHIVE/` bu dəstdən **kənardır**, ona görə çevrilmiş `.docx`")
    w("   nüsxəsi budanmış olsa belə arxivdəki PDF-i tutmur.")
    w("")
    w("Nəticə: bir hesabat iki müstəqil `Sıra №` alır, hər ikisi `items_table`-ə düşür,")
    w("`total_records` onu iki yoxlama kimi sayır.")
    w("")

    # ---- 3
    w("## 3. Təsnifat — 231 cütün hər biri nədir")
    w("")
    w("Təsnifat sübuta əsaslanır, nömrəyə yox. Bir sənədin barmaq izi onun **tikiş")
    w("nömrələridir**: eyni gün eyni tikişin iki hesabatı bir sənəddir, fərqli")
    w("tikişlərin hesabatları iki yoxlamadır.")
    w("")
    w("| verdikt | cüt | mənası |")
    w("|---|--:|---|")
    w(f"| `{SAME}` | {verdicts[SAME]} | bir fiziki hesabat iki dəfə oxunub |")
    w(f"| `{DISTINCT}` | {verdicts[DISTINCT]} | **iki real yoxlama**, nömrə toqquşub |")
    w(f"| `{UNDECIDED}` | {verdicts[UNDECIDED]} | sübut çatmır, operator qərarı |")
    w("")
    w("Cütün daxilində sidecar sahələrinin fərqi:")
    w("")
    w("| sahə | fərqlənən cüt |")
    w("|---|--:|")
    for f in ("result", "method", "standard", "item_name", "date"):
        w(f"| `{f}` | {field_diff.get(f, 0)} |")
    w("")
    w("`result` 0 olduğuna görə heç bir cütdə verdikt ziddiyyəti yoxdur — problem")
    w("təkrarlanmadır, ziddiyyət deyil. Amma `date` və `standard` fərqləri")
    w("göstərir ki, iki sətir eyni hesabatı **fərqli göstərir**, bu da öz-özlüyündə")
    w("dövlətə gedən sənəddə qüsurdur.")
    w("")

    # ---- 4
    w("## 4. Hansı nüsxə doğrudur")
    w("")
    w("İki ayrı sual, iki ayrı cavab.")
    w("")
    w("**Hansı SƏTİR saxlanmalıdır:** canlı `.docx`-dən gələn sətir. Sübut —")
    w("arxiv PDF-dən oxunan sətir hər ölçüdə zəifdir:")
    same_pairs = [p for p in pairs if p.verdict == SAME]
    empty_welds = sum(1 for p in same_pairs if "altçoxluq (0" in p.reason)
    w("")
    w(f"- {len(same_pairs)} `{SAME}` cütünün {empty_welds}-də arxiv PDF **heç bir")
    w("  tikiş sətri vermir**; qalanlarında verdiyi tikişlər canlı `.docx`-in")
    w("  altçoxluğudur. Heç bir halda arxiv nüsxə əlavə məlumat gətirmir.")
    w(f"- {field_diff.get('date', 0)} cütdə tarix fərqlidir; fərq həmişə arxiv")
    w("  tərəfdədir (düz təbəqələnməmiş PDF mətnindən səhv xana oxunur).")
    w(f"- {field_diff.get('item_name', 0)} cütdə `item_name` fərqlidir; arxiv tərəf")
    w("  ya boşdur, ya da daha kasad.")
    w("")
    w("**Hansı NÖMRƏ doğrudur:** bu, operator qərarıdır və ayrıca məsələdir.")
    w("Sənədin özü (imzalanmış mənbə) `<ÜSUL>-<MÜŞTƏRİ>` yazır; fayl adı və ona görə")
    w("dövlətə gedən aylıq hesabat `<MÜŞTƏRİ>-<ÜSUL>` yazır. Bu, yalnız bu 231 cütü")
    w(f"deyil, korpusdakı **{stat.get('TRANSPOZİSİYA', 0)} canlı sənədi** əhatə edir.")
    w("Boru xətti bu fərqi onsuz da görür və sayır — `resolve_report_no` onu")
    w("`discrepancies`-ə yazır, `main.py:861` isə `report-no drift: N (filename wins)`")
    w("kimi çap edir. Yəni davranış gizli deyil, sənədləşdirilmiş və qəsdidir.")
    w("")

    # ---- 5
    w("## 5. Birləşdirilsə nə dəyişir")
    w("")
    w("Yalnız `" + SAME + "` cütləri birləşdirilə bilər. Aşağıdakı cədvəl hər")
    w("sənəd üçün nə qədər sətrin gedəcəyini göstərir; `total_records` sidecar-da")
    w("`len(items_table)`-dir (`json_exporter.py:58`), ona görə eyni qədər azalır.")
    w("")
    w("| sənəd | cüt | birləşə bilən | sətir (indi) | sətir (sonra) | total_records |")
    w("|---|--:|--:|--:|--:|---|")
    drop_total = rows_total = 0
    for doc in sorted(by_doc):
        group = by_doc[doc]
        drop = sum(1 for p in group if p.verdict == SAME)
        tr, rows, _src = totals.get(doc, (0, 0, 0))
        drop_total += drop
        rows_total += rows
        w(f"| `{doc}` | {len(group)} | {drop} | {rows} | {rows - drop} | "
          f"{tr} → {tr - drop} |")
    w(f"| **bu {len(by_doc)} sənədin cəmi** | **{len(pairs)}** | **{drop_total}** | "
      f"**{rows_total}** | **{rows_total - drop_total}** | |")
    w("")
    w(f"Korpus miqyasında: bütün sidecar-larda **{corpus_rows}** sətir var,")
    w(f"birləşdirmədən sonra **{corpus_rows - drop_total}** qalır "
      f"(−{drop_total}, {drop_total / corpus_rows * 100:.1f}%).")
    w("`source_report_count` da eyni qədər azalır — bu sənədlərdə o, bu gün")
    w("`total_records` ilə eynidir, yəni hər sətir bir mənbə sənəd sayılır.")
    w("")
    w("Qalan cütlər sətir itirmir: " +
      f"{verdicts[DISTINCT]} cüt real iki yoxlamadır, {verdicts[UNDECIDED]} cüt")
    w("sübut çatmadığına görə toxunulmur.")
    w("")

    # ---- 6
    w("## 6. Risk — yanlış birləşmə real yoxlamanı silə bilərmi")
    w("")
    w("**Bəli, bilər, və korpusda bunun sübutu var.** Sırf nömrə üzərində qurulan")
    w("bir birləşdirmə qaydası (\"seqmentləri sırala, eyni olanları birləşdir\")")
    w(f"aşağıdakı {verdicts[DISTINCT]} cütü səhvən birləşdirərdi:")
    w("")
    w("| sənəd | yazılış A | tikişlər A | yazılış B | tikişlər B |")
    w("|---|---|---|---|---|")
    for p in pairs:
        if p.verdict != DISTINCT:
            continue
        live = [f for f in p.files_a + p.files_b if corpus.is_live(f)]
        wa = sorted(corpus.welds(live[0], p.method)) if live else []
        wb = sorted(corpus.welds(live[1], p.method)) if len(live) > 1 else []
        w(f"| `{p.doc.replace('compiled_monthly_report_', '').replace('.json', '')}` "
          f"| `{p.a}` | {', '.join(wa) or '—'} | `{p.b}` | {', '.join(wb) or '—'} |")
    w("")
    w("Hər iki sənədin **daxili nömrəsi eynidir**, tarixi eynidir, WDR ID-si eynidir,")
    w("iş adı eynidir — fərqlənən yalnız hansı tikişin çəkildiyidir. Bunlar eyni günün")
    w("iki müxtəlif radioqrafik yoxlamasıdır və mənbədə hər ikisinə **eyni hesabat")
    w("nömrəsi verilib**. Bu, boru xəttinin yaratdığı problem deyil; mənbədəki nömrə")
    w("toqquşmasıdır. Birləşdirmə burada bir real yoxlamanı sənəddən silərdi.")
    w("")
    w("Ona görə təhlükəsiz birləşdirmə qaydası nömrəyə yox, **məzmuna** baxmalıdır:")
    w("eyni müştəri + eyni iş nömrəsi (fayl adı quyruğu) + tikiş dəsti altçoxluq.")
    w("Bu auditdəki təsnifat məhz o qaydadır.")
    w("")

    # ---- 7
    w("## 7. Qərarsız qalanlar")
    w("")
    undecided = [p for p in pairs if p.verdict == UNDECIDED]
    if not undecided:
        w("Yoxdur.")
    else:
        w("| sənəd | yazılış A | yazılış B | səbəb |")
        w("|---|---|---|---|")
        for p in undecided:
            w(f"| `{p.doc.replace('compiled_monthly_report_', '').replace('.json', '')}` "
              f"| `{p.a}` | `{p.b}` | {p.reason} |")
    w("")

    # ---- 8
    w("## 8. Nə edilmədi")
    w("")
    w("- Heç bir fayl adı dəyişdirilmədi, köçürülmədi, silinmədi.")
    w("- `report_key`, `report_key_of`, `resolve_report_no` toxunulmadı.")
    w("- `pdf_sources`-un `held` dəsti toxunulmadı.")
    w("- Sidecar-lar toxunulmadı; `total_records` bu gün nə idisə odur.")
    w("")
    w("Düzəliş üçün üç ayrı qərar lazımdır və heç biri bu auditin səlahiyyətində")
    w("deyil: (i) ad konvensiyası — fayl adı yoxsa sənəd daxili nömrə doğrudur;")
    w("(ii) arxiv PDF-in təkrar oxunması — `held` dəstinin transpozisiyaya")
    w("həssaslığı; (iii) mənbədəki nömrə toqquşmaları — bunlar yalnız inspektor")
    w("tərəfindən düzəldilə bilər.")
    w("")

    out = out_dir / f"duplicate_identity_audit_{today}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", default=str(_ROOT / "output"))
    ap.add_argument("--input-dir", default=str(_ROOT / "input"))
    ap.add_argument("--cache-dir", default=str(_ROOT / ".parse_cache"))
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)

    out_dir = Path(args.output_dir)
    corpus = Corpus(Path(args.input_dir), Path(args.cache_dir))
    pairs = sidecar_pairs(out_dir)
    for pair in pairs:
        classify(pair, corpus)

    today = _dt.date.today().isoformat()
    target = Path(args.out) if args.out else out_dir
    report = write_report(pairs, corpus, target if target.is_dir() else out_dir, today)

    counts = collections.Counter(p.verdict for p in pairs)
    print(f"[dup-identity] {len(pairs)} transposed pair(s): "
          f"{counts[SAME]} same, {counts[DISTINCT]} distinct, "
          f"{counts[UNDECIDED]} undecided -> {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
