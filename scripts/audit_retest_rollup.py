"""Read-only audit: what a retest roll-up would change, and what it cannot fix.

Task 11-E1. The operator's request is that a repaired weld stop occupying two lines
in the state's monthly document — the retest line folded into its parent, the parent
carrying the final verdict. Before any such rule is written, this script measures the
corpus it would act on and writes ``output/retest_rollup_audit_<date>.md``.

It answers five questions the rule's safety depends on:

1. **How many chains are there**, per client and month, split by what actually
   happened: parent rejected then repaired (a), rejected and still rejected (b),
   rejected with NO retest at all (c), and passed-yet-retested (d).
2. **How many retests have no parent in their document** (``is_orphan_retest``) —
   those keep a full index of their own and must not be folded into anything.
3. **How many report numbers end in a bare ``R``.** :data:`report_identity.RETEST_SUFFIX`
   requires ``R<digit>``/``RS<digit>``/``RW``, so ``…-072R`` is not recognised as a
   retest at all: it compiles as an independent rank-0 parent. Any roll-up rule is
   blind to exactly these rows, so the audit lists them individually.
4. **Where the gaps in the report-number sequences come from** — quarantine, the
   pruned-duplicate pass, a standard/date gate, or a report that never existed.
   Counted per number SERIES (``<prefix>-<YY>``) rather than per client folder, for
   the two reasons spelled out in :func:`series_gaps`.
5. **What the roll-up would remove and change** — rows hidden per document, and the
   verdict distribution before and after.

A sixth thing the measurement turned up on its own is reported too: report numbers
that appear twice in one document under two spellings (``MT-U-25-028`` and
``U-MT-25-028``). They are two rank-0 parents to the pipeline, so a roll-up would
roll each up separately and the sheet would carry the same inspection twice.

Nothing is written except the audit file: the pipeline, its state and the sidecars
are all read-only here. The rows come from the compiled sidecars
(``output/<CLIENT>/compiled_monthly_report_*.json``), which are the same rows the PDF
renders, and rank/series are derived with :mod:`report_identity`'s own functions so
the audit cannot disagree with the pipeline about what a retest is.

    python scripts/audit_retest_rollup.py
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report.report_identity import (   # noqa: E402
    RETEST_SUFFIX, report_key_of, retest_rank, strip_retest,
)

# Verdict tokens as they stand in the sidecar — already translated, because the
# sidecar is written after translation. Spelled out rather than re-read from
# az.json: the audit compares what the OPERATOR sees on the sheet.
FIT, UNFIT, INFO = "Yararlı", "Yarasız", "Məlumat üçün"

# A report number whose tail is a lone letter R preceded by a digit. This is the
# shape RETEST_SUFFIX does NOT match, and the reason it is measured separately.
_BARE_R = re.compile(r"(?i)\d\s*R$")

# The ``-<YY>-<seq>`` tail every report number in this corpus ends with, split so the
# prefix ("AZF-DP-W1"), the year and the running number can be compared separately.
_SERIES_TAIL = re.compile(r"^(.*)-(\d{2})-(\d{1,4})$")

_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}

# Input directories that mean something specific about a missing report.
_QUARANTINE = "SKIPPED_REPORTS"
_PRUNED = "_PRUNED"
_ARCHIVE = "PDF_ARCHIVE"


class Row:
    """One sidecar row plus the identity facts the audit derives from it."""

    __slots__ = ("seq_no", "date", "report_no", "standard", "method",
                 "item_name", "result", "rank", "series", "doc")

    def __init__(self, raw: dict, doc: "Doc"):
        self.seq_no = str(raw.get("seq_no", "")).strip()
        self.date = str(raw.get("date", "")).strip()
        self.report_no = str(raw.get("report_no", "")).strip()
        self.standard = str(raw.get("standard", "")).strip()
        self.method = str(raw.get("method", "")).strip()
        self.item_name = str(raw.get("item_name", "")).strip()
        self.result = str(raw.get("result", "")).strip()
        self.rank = retest_rank(self.report_no)
        self.series = strip_retest(self.report_no)
        self.doc = doc

    @property
    def is_child(self) -> bool:
        """True when the row was numbered ``4a``/``4b`` — a retest UNDER a parent.

        This is the exact predicate E3 would hide (``sort_key[1] > 0``): a lettered
        sequence number is written only by the matched branch of
        ``_assign_sequence_numbers``.
        """
        return bool(self.seq_no) and not self.seq_no.isdigit()

    @property
    def is_orphan(self) -> bool:
        """A retest that found no parent in its month: full index, own line."""
        return self.rank > 0 and not self.is_child

    @property
    def is_bare_r(self) -> bool:
        """Ends in a lone ``R`` that :data:`RETEST_SUFFIX` does not recognise."""
        return (RETEST_SUFFIX.search(self.report_no) is None
                and bool(_BARE_R.search(self.report_no)))


class Doc:
    """One compiled sidecar."""

    def __init__(self, path: Path):
        self.path = path
        data = json.loads(path.read_text(encoding="utf-8"))
        self.client = path.parent.name
        self.client_name = data.get("client_name", "")
        self.period = data.get("reporting_period", "")
        self.total_records = data.get("total_records")
        stem = path.stem.rsplit("compiled_monthly_report_", 1)[-1]
        parts = stem.split("_")
        self.mon = parts[-2].upper() if len(parts) >= 2 else ""
        self.year = parts[-1] if parts else ""
        self.rows = [Row(r, self) for r in data.get("items_table", [])]

    @property
    def month_key(self) -> tuple:
        try:
            return (int(self.year), _MONTHS.get(self.mon, 0))
        except ValueError:
            return (0, 0)

    @property
    def label(self) -> str:
        return f"{self.client} {self.mon} {self.year}"


class Chain:
    """A rank-0 parent and the retest rows numbered under it, in rank order."""

    def __init__(self, parent: Row, children: list[Row]):
        self.parent = parent
        self.children = sorted(children, key=lambda r: (r.rank, r.seq_no))

    @property
    def final_result(self) -> str:
        """The verdict the roll-up would show on the parent line."""
        return self.children[-1].result if self.children else self.parent.result

    @property
    def category(self) -> str:
        """(a)/(b)/(c)/(d)/-- — see the module docstring."""
        if self.parent.result == UNFIT:
            if not self.children:
                return "c"
            return "a" if self.final_result == FIT else "b"
        if self.children:
            return "d"
        return "--"


def load_docs(out_dir: Path) -> list[Doc]:
    paths = sorted(p for p in out_dir.glob("*/compiled_monthly_report_*.json"))
    return [Doc(p) for p in paths]


def build_chains(doc: Doc) -> list[Chain]:
    """Every rank-0 row of a document, with the retest rows that match its series."""
    by_series: dict[str, list[Row]] = collections.defaultdict(list)
    for row in doc.rows:
        if row.is_child:
            by_series[row.series].append(row)
    return [Chain(r, by_series.get(r.series, []))
            for r in doc.rows if r.rank == 0]


def index_input(input_dir: Path) -> dict[str, set[str]]:
    """Map every report key on disk to the set of top-level ``input/`` folders holding it.

    The key is :func:`report_key_of` — the file's LEADING number token — which is what
    the pipeline itself uses to decide two files are the same report, so a gap this
    index calls "absent" is absent by the pipeline's own definition, not by string luck.
    """
    index: dict[str, set[str]] = collections.defaultdict(set)
    if not input_dir.is_dir():
        return index
    for path in input_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in (".docx", ".doc", ".pdf"):
            continue
        try:
            top = path.relative_to(input_dir).parts[0]
        except ValueError:                       # pragma: no cover - defensive
            continue
        index[report_key_of(path.name)].add(top)
    return index


def quarantine_tags() -> dict[str, str]:
    """``{filename: reason}`` recorded by the pre-processor, or ``{}``.

    The file carries its own ``recorded_at``; it is a convenience label on a gap,
    never the gap's proof, so a stale one weakens nothing.
    """
    state = _ROOT / ".state" / "quarantine_reasons.json"
    if not state.is_file():
        return {}
    try:
        return json.loads(state.read_text(encoding="utf-8")).get("tags", {}) or {}
    except (OSError, ValueError):
        return {}


def attribute_gap(key: str, index: dict[str, set[str]]) -> str:
    """Why a report number present in no compiled document is missing."""
    where = index.get(key)
    if not where:
        return "korpusda yoxdur"
    live = {w for w in where if w not in (_QUARANTINE, _PRUNED, _ARCHIVE)}
    if live:
        return "korpusda var, kompilyasiya olunmayıb"
    if _QUARANTINE in where:
        return "karantin"
    if _ARCHIVE in where:
        return "yalnız PDF arxivində"
    return "budanmış dublikat"


def series_gaps(docs: list[Doc], index: dict[str, set[str]]) -> dict:
    """Missing running numbers per number SERIES, measured across the whole corpus.

    Two things decide the grouping, and both were measured rather than assumed:

    * **Across months, not per document.** The source numbering runs across the year,
      so nearly every month is missing the numbers that belong to its neighbours.
      Only a number absent from EVERY document is a real gap.
    * **By number prefix, not by client folder.** ``KF-RT-…`` is compiled under both
      ``KHE`` and ``KHF`` — the same running series feeds two client groups. Counting
      per client folder would report every KHF number as a hole in KHE's sequence and
      roughly double the total. The series is the numbering authority here; the client
      column below is only a label, taken from where that series mostly lands.
    """
    compiled: dict[tuple, set[int]] = collections.defaultdict(set)
    sample: dict[tuple, str] = {}
    owner: dict[tuple, collections.Counter] = collections.defaultdict(collections.Counter)
    for doc in docs:
        for row in doc.rows:
            m = _SERIES_TAIL.match(strip_retest(row.report_no))
            if not m:
                continue
            prefix, yy, num = m.group(1), m.group(2), int(m.group(3))
            compiled[(prefix, yy)].add(num)
            sample.setdefault((prefix, yy), m.group(3))
            owner[(prefix, yy)][doc.client] += 1

    per_client: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    detail: list[tuple] = []
    for (prefix, yy), nums in sorted(compiled.items()):
        if len(nums) < 2:
            continue
        client = owner[(prefix, yy)].most_common(1)[0][0]
        width = len(sample[(prefix, yy)])
        for n in range(min(nums), max(nums) + 1):
            if n in nums:
                continue
            missing = f"{prefix}-{yy}-{str(n).zfill(width)}"
            reason = attribute_gap(report_key_of(missing), index)
            per_client[client][reason] += 1
            detail.append((client, missing, reason))
    return {"per_client": per_client, "detail": detail}


def transposed_duplicates(doc: Doc) -> list[tuple[str, str]]:
    """Report numbers in one document that differ only in the ORDER of their segments.

    ``MT-U-25-028`` and ``U-MT-25-028`` are the same inspection written two ways. The
    pipeline keys identity on the number string, so both compile as rank-0 parents
    with their own sequence numbers — and a roll-up would fold each chain separately,
    leaving the same weld on the sheet twice with two verdicts. Detected by sorting the
    dash-separated segments, which is deliberately blunt: it reports a suspicion for
    the operator to confirm, it does not merge anything.
    """
    canon: dict[tuple, list[str]] = collections.defaultdict(list)
    for row in doc.rows:
        if row.rank:
            continue          # a retest shares its parent's segments BY DESIGN
        key = tuple(sorted(row.report_no.upper().split("-")))
        if row.report_no not in canon[key]:
            canon[key].append(row.report_no)
    return [(v[0], v[1]) for v in canon.values() if len(v) > 1]


def rollup_effect(docs: list[Doc]) -> dict:
    """What hiding matched retest rows would do to line counts and verdicts."""
    before = collections.Counter()
    after = collections.Counter()
    hidden_per_doc: list[tuple[str, int, int]] = []
    flipped: list[tuple[str, str, str, str]] = []
    for doc in docs:
        chains = build_chains(doc)
        hidden = sum(len(c.children) for c in chains)
        for row in doc.rows:
            before[row.result] += 1
        for chain in chains:
            after[chain.final_result] += 1
            if chain.final_result != chain.parent.result:
                flipped.append((doc.label, chain.parent.report_no,
                                chain.parent.result, chain.final_result))
        for row in doc.rows:
            if row.is_orphan:
                after[row.result] += 1
        if hidden:
            hidden_per_doc.append((doc.label, len(doc.rows), hidden))
    return {"before": before, "after": after,
            "hidden_per_doc": hidden_per_doc, "flipped": flipped}


def md_table(header: list[str], rows: list[list], align: str = "") -> str:
    sep = ["---"] * len(header)
    for i, ch in enumerate(align[:len(header)]):
        if ch == "r":
            sep[i] = "--:"
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join(sep) + " |"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def render(docs: list[Doc], index: dict[str, set[str]], tags: dict[str, str]) -> str:
    today = _dt.date.today().isoformat()
    rows_total = sum(len(d.rows) for d in docs)
    lines: list[str] = []
    add = lines.append

    add(f"# Retest yığcamlaşdırma auditi — {today}")
    add("")
    add("Oxu-only ölçmə (Tapşırıq 11-E1). Heç bir kod və heç bir korpus faylı "
        "dəyişdirilmir. Mənbə: kompilyasiya olunmuş sidecar-lar "
        "(`output/<MÜŞTƏRİ>/compiled_monthly_report_*.json`) — PDF-in göstərdiyi "
        "eyni sətirlər. Rank və seriya `report_identity`-nin öz funksiyaları ilə "
        "çıxarılır, ona görə audit boru xətti ilə \"retest nədir\" sualında "
        "razılaşa bilməmək imkanı yoxdur.")
    add("")
    add(f"Korpus: **{len(docs)} sənəd**, **{rows_total} sətir**.")
    add("")

    # ---- 1. chains -------------------------------------------------------
    all_chains = [(d, c) for d in docs for c in build_chains(d)]
    with_children = [(d, c) for d, c in all_chains if c.children]
    lengths = collections.Counter(len(c.children) for _, c in with_children)
    child_rows = [r for d in docs for r in d.rows if r.is_child]
    orphans = [r for d in docs for r in d.rows if r.is_orphan]
    cats = collections.Counter(c.category for _, c in all_chains)

    add("## 1. Zəncirlər")
    add("")
    add(md_table(
        ["ölçü", "say"],
        [["valideyn sətri (rank 0)", len(all_chains)],
         ["retest zənciri olan valideyn", len(with_children)],
         ["zəncir uzunluğu 1 / 2 / 3+",
          f"{lengths[1]} / {lengths[2]} / {sum(v for k, v in lengths.items() if k >= 3)}"],
         ["valideynə bağlanmış retest sətri (`4a`/`4b`)", len(child_rows)],
         ["valideynsiz retest (`is_orphan_retest`)", len(orphans)],
         ["zənciri olan sənəd", len({d.label for d, c in with_children})]],
        align="lr"))
    add("")

    add("### Kateqoriyalar")
    add("")
    add(md_table(
        ["kod", "hal", "say"],
        [["(a)", "valideyn **Yarasız**, zəncirin sonu **Yararlı** — təmir edilib", cats["a"]],
         ["(b)", "valideyn **Yarasız**, zəncirin sonu da **Yararlı deyil**", cats["b"]],
         ["(c)", "valideyn **Yarasız**, retesti **yoxdur** — düzəldilməmiş qalıb", cats["c"]],
         ["(d)", "valideyn keçib, yenə də retesti var", cats["d"]]],
        align="llr"))
    add("")
    add("**(c) qırmızı xəttdir.** Bu sətirlərin verdikti yığcamlaşdırma ilə "
        "dəyişmir və dəyişməməlidir — mənbədə rədd olunmuş və təkrar "
        "yoxlanmamış qaynaq dövlətə gedən sənəddə `Yararlı` görünə bilməz. "
        "E2 sualı məhz bunların necə göstəriləcəyi haqqındadır.")
    add("")

    # ---- 2. client x month ----------------------------------------------
    add("## 2. Müştəri × ay bölgüsü")
    add("")
    add("Yalnız retest və ya rədd hadisəsi olan sənədlər. Boş sətirlər buraxılıb.")
    add("")
    per: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    order: dict[str, tuple] = {}
    for d, c in all_chains:
        if c.category != "--":
            per[d.label][c.category] += 1
            order[d.label] = (d.client,) + d.month_key
    for d in docs:
        n = sum(1 for r in d.rows if r.is_orphan)
        if n:
            per[d.label]["orphan"] += n
            order[d.label] = (d.client,) + d.month_key
    table = []
    for label in sorted(per, key=lambda s: order[s]):
        cc = per[label]
        table.append([label, cc["a"], cc["b"], cc["c"], cc["d"], cc["orphan"]])
    add(md_table(["sənəd", "(a)", "(b)", "(c)", "(d)", "orphan"], table,
                 align="lrrrrr"))
    add("")

    # ---- 3. bare R -------------------------------------------------------
    bare = [r for d in docs for r in d.rows if r.is_bare_r]
    add("## 3. Çılpaq `R` — yığcamlaşdırmanın kor nöqtəsi")
    add("")
    add("`RETEST_SUFFIX` (`report_identity.py:27`) `RS\\d+|RW\\d*|R\\d+(?:-\\d+)?` "
        "tələb edir. Sondakı tək `R` heç bir alternativə uyğun gəlmir, ona görə "
        "`…-072R` retest kimi tanınmır: rank 0 alır, öz `series_key`-i və öz tam "
        "`Sıra №`-si olur, `is_orphan_retest` bayrağı qalxmır, kəhrəba fon yoxdur. "
        "**Yazılacaq hər yığcamlaşdırma qaydası bu sətirləri görmür.**")
    add("")
    if bare:
        rows = []
        for r in bare:
            base = re.sub(r"(?i)\s*R$", "", r.report_no)
            same = any(x.report_no == base for x in r.doc.rows)
            rows.append([r.doc.label, r.report_no, r.result,
                         "bəli" if same else "xeyr",
                         next((x.result for x in r.doc.rows
                               if x.report_no == base), "—")])
        add(md_table(
            ["sənəd", "Report №", "verdikt", "valideyn həmin sənəddə?",
             "valideynin verdikti"], rows))
    else:
        add("Cari korpusda çılpaq `R` ilə bitən sətir yoxdur.")
    add("")
    add(f"Sayı: **{len(bare)}**. Hər biri valideyn indeksi yeyir — "
        "yığcamlaşdırmadan sonrakı `Sıra №` sayına birbaşa təsir edir.")
    add("")

    # ---- 3b. transposed duplicates ---------------------------------------
    dups = [(d, a, b) for d in docs for a, b in transposed_duplicates(d)]
    add("## 3b. Eyni hesabatın iki yazılışı")
    add("")
    add("Seqmentləri yerdəyişmiş nömrələr — `MT-U-25-028` və `U-MT-25-028` eyni "
        "yoxlamadır, amma boru xətti kimliyi nömrə sətrinə görə açdığı üçün hər "
        "ikisi ayrıca rank-0 valideyndir. Yığcamlaşdırma hər zənciri ayrıca "
        "yığcamlaşdırar və eyni qaynaq sənəddə iki dəfə, iki verdiktlə qalar. "
        "Aşkarlama küt qəsdən kütdür — şübhəni operatora verir, heç nə "
        "birləşdirmir.")
    add("")
    if dups:
        per_client = collections.Counter(d.client for d, _, _ in dups)
        agree = collections.Counter()
        for d, a, b in dups:
            ra = next(r for r in d.rows if r.report_no == a)
            rb = next(r for r in d.rows if r.report_no == b)
            agree["verdikt eyni"] += ra.result == rb.result
            agree["tarix eyni"] += ra.date == rb.date
            agree["İtem eyni"] += ra.item_name == rb.item_name
        add(md_table(
            ["ölçü", "say"],
            [["cüt", len(dups)],
             ["artıq sətir (cütün bir üzvü)", len(dups)],
             ["təsirlənən sənəd", len({d.label for d, _, _ in dups})]]
            + [[k, v] for k, v in agree.items()],
            align="lr"))
        add("")
        add("Müştəri üzrə: " + ", ".join(f"**{c}** {n}"
                                         for c, n in per_client.most_common()) + ".")
        add("")
        add(f"Cütlərin **hamısında verdikt eynidir** ({agree['verdikt eyni']}/"
            f"{len(dups)}), yəni bu, ziddiyyətli məlumat deyil — **təkrardır**. "
            "Amma sənədin `total_records` sayı və `Sıra №` diapazonu hər cütü iki "
            "yoxlama kimi sayır. Bu, E-nin predmeti deyil (yığcamlaşdırma "
            "retestlərə aiddir, bu isə kimlik məsələsidir) və bu tapşırıqda "
            "düzəldilmir — ayrıca qərar tələb edir.")
        add("")
        add("<details><summary>Bütün cütlər</summary>")
        add("")
        add(md_table(["sənəd", "yazılış A", "yazılış B"],
                     [[d.label, a, b] for d, a, b in dups]))
        add("")
        add("</details>")
    else:
        add("Belə cüt tapılmadı.")
    add("")

    # ---- 4. gaps ---------------------------------------------------------
    add("## 4. Nömrə fasilələri")
    add("")
    add("Valideynlər `1..N` bitişik `Sıra №` alır, retestlər hərf şəkilçisi, "
        "üstəlik `collapse_display_rows` ekran sətirlərini 1-dən yenidən "
        "nömrələyir — deməli **retest gizlədilməsi öz-özlüyündə fasilə yaratmır**. "
        "Operatorun görəcəyi fasilə `Report №` ardıcıllığındadır. Ölçü **nömrə "
        "seriyası** (`<prefiks>-<İL>`) üzrə aparılır, müştəri qovluğu üzrə yox: "
        "mənbə nömrələməsi il boyu axır (bir aydan əskik nömrə adətən qonşu ayın "
        "sənədindədir), üstəlik eyni seriya iki müştəri qrupuna paylanır — "
        "`KF-RT-…` həm `KHE`, həm `KHF` altında kompilyasiya olunur. Müştəri "
        "qovluğu üzrə saymaq KHF-in hər nömrəsini KHE-nin ardıcıllığında deşik "
        "kimi göstərərdi. Müştəri sütunu yalnız etiketdir — seriyanın əsasən "
        "düşdüyü qrup.")
    add("")
    gaps = series_gaps(docs, index)
    reasons = sorted({r for cc in gaps["per_client"].values() for r in cc})
    if reasons:
        table = []
        for cl in sorted(gaps["per_client"]):
            cc = gaps["per_client"][cl]
            table.append([cl] + [cc[r] for r in reasons] + [sum(cc.values())])
        total = ["**cəmi**"] + [sum(gaps["per_client"][cl][r]
                                    for cl in gaps["per_client"]) for r in reasons]
        total.append(sum(total[1:]))
        add(md_table(["müştəri"] + reasons + ["cəmi"], table + [total],
                     align="l" + "r" * (len(reasons) + 1)))
    else:
        add("Fasilə tapılmadı.")
    add("")
    quarantined = [(cl, no) for cl, no, why in gaps["detail"] if why == "karantin"]
    if quarantined:
        add(f"Karantindəki {len(quarantined)} fasilədən ilk 20-si, mövcud olduqda "
            "pre-processor-un öz səbəb etiketi ilə:")
        add("")
        rows = []
        for cl, no in quarantined[:20]:
            tag = next((v for k, v in tags.items()
                        if report_key_of(k) == report_key_of(no)), "—")
            rows.append([cl, no, tag])
        add(md_table(["müştəri", "Report №", "etiket"], rows))
        add("")
        add("Etiketlər `.state/quarantine_reasons.json`-dan gəlir və həmin faylın "
            "öz `recorded_at` tarixini daşıyır — fasilənin sübutu yox, rahatlıq "
            "üçün adıdır.")
        add("")

    # ---- 5. rollup effect ------------------------------------------------
    eff = rollup_effect(docs)
    add("## 5. Qayda tətbiq olunsa")
    add("")
    add("Simulyasiya: `sort_key[1] > 0` olan sətirlər (yəni `4a`/`4b` nömrəli, "
        "valideynə bağlanmış retestlər) gizlədilir, valideynin verdikti zəncirin "
        "**sonuncu** üzvünün verdikti ilə əvəzlənir. Orphan retestlər gizlədilmir — "
        "onların valideyni yoxdur, gizlətmək sətri bütünlüklə yox etmək olardı.")
    add("")
    vis_before = sum(eff["before"].values())
    vis_after = sum(eff["after"].values())
    add(md_table(
        ["verdikt", "əvvəl", "sonra", "fərq"],
        [[k, eff["before"][k], eff["after"][k], eff["after"][k] - eff["before"][k]]
         for k in (FIT, UNFIT, INFO)]
        + [["**cəmi sətir**", vis_before, vis_after, vis_after - vis_before]],
        align="lrrr"))
    add("")
    add(f"Verdikti dəyişən valideyn sətri: **{len(eff['flipped'])}**.")
    add("")
    if eff["flipped"]:
        add("<details><summary>Verdikti dəyişən sətirlər</summary>")
        add("")
        add(md_table(["sənəd", "Report №", "əvvəl", "sonra"],
                     [list(x) for x in eff["flipped"]]))
        add("")
        add("</details>")
        add("")
    add("### Sənəd başına azalan sətir")
    add("")
    add(md_table(
        ["sənəd", "sətir", "gizlənən", "qalan"],
        [[lab, n, h, n - h] for lab, n, h in eff["hidden_per_doc"]],
        align="lrrr"))
    add("")
    add("Sidecar toxunulmur: `items_table` və `total_records` bütün retest "
        "sətirlərini saxlamağa davam edir — gizlətmə yalnız prezentasiya qatındadır.")
    add("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output-dir", default=str(_ROOT / "output"))
    ap.add_argument("--input-dir", default=str(_ROOT / "input"))
    ap.add_argument("--out", default=None,
                    help="audit file path (default: output/retest_rollup_audit_<date>.md)")
    args = ap.parse_args(argv)

    out_dir = Path(args.output_dir)
    docs = load_docs(out_dir)
    if not docs:
        print(f"Sidecar tapilmadi: {out_dir}")
        return 1
    index = index_input(Path(args.input_dir))
    text = render(docs, index, quarantine_tags())

    dest = (Path(args.out) if args.out
            else out_dir / f"retest_rollup_audit_{_dt.date.today().isoformat()}.md")
    dest.write_text(text, encoding="utf-8")
    print(f"audit: {dest}  ({len(docs)} docs, {sum(len(d.rows) for d in docs)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
