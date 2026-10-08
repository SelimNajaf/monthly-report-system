"""Read-only audit: what the trailing-colon rule changes in the İtem/Detal column.

Task 11-B1 approves one line in :func:`extractor.item_is_bad` — a value that ends in
``:`` is the NEXT caption, not this item's value. This script measures the change
before it ships and after: it replays the aggregator's three-step item chain
(global Item -> Description -> most common weld item, ``document_aggregator``
:func:`_row_from_doc`) over every cached document, once with the current rule and
once with the colon rule, and writes the differing rows to
``output/item_detail_diff_<date>.md``.

Nothing is written to the corpus and no pipeline state is touched. The document
bodies come from ``.parse_cache/<sha256>.json``, which is exactly what the pipeline
itself reads, so the replay sees the same tables the compile sees.

    python scripts/audit_item_detail.py

Exit code is 1 when more rows change than ``--max-changed`` (default 30) — the
approved rule was measured at 30, so a wider cut means it is biting something else.

**Second output (task 11-B2).** The same replay already holds every İtem/Detal value
the corpus produces, so it also writes ``output/item_translation_review_<date>.md``:
every value the dictionary does NOT cover, with its count, its clients, a PROPOSED
Azerbaijani rendering and an empty operator column. ``translations/az.json`` is not
touched — the review is a proposal sheet, and a line enters the dictionary only after
the operator has approved it in that column.
"""

from __future__ import annotations

import argparse
import collections
import difflib
import datetime as _dt
import hashlib
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report import config, extractor  # noqa: E402
from monthly_report.method_registry import detect_method  # noqa: E402
from monthly_report.report_identity import squash  # noqa: E402
from monthly_report.translator import load_dictionary  # noqa: E402

_SHIPPED = extractor.item_is_bad

# The two rules are spelled out here rather than captured from the module, so the
# comparison keeps working after the colon rule ships in :mod:`extractor`.
def item_is_bad_legacy(value: str) -> bool:
    """The deny-list alone — ``item_is_bad`` as it stood before task 11-B1."""
    return extractor._norm(value) in extractor._ITEM_BADSET


def item_is_bad_with_colon_rule(value: str) -> bool:
    """The deny-list plus the trailing-colon caption rule."""
    if (value or "").rstrip().endswith(":"):
        return True
    return item_is_bad_legacy(value)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def resolve_item(tables, meta: dict, method: str) -> tuple[str, str]:
    """``(item_detail, source)`` — the aggregator's chain, replayed step for step.

    Mirrors ``document_aggregator._row_from_doc``; ``source`` names which of the
    three steps produced the value so the audit can say WHERE a change came from.
    """
    item = extractor.extract_item_global(tables)
    if not extractor.item_is_bad(item):
        return item, "global"
    item = squash(meta.get("description", ""))
    if not extractor.item_is_bad(item):
        return item, "description"
    welds = (extractor.extract_rt_welds(tables) if method == "RT"
             else extractor.extract_welds(tables))
    valid = [squash(w.get("item", "")) for w in welds
             if not extractor.item_is_bad(w.get("item", ""))]
    if valid:
        return collections.Counter(valid).most_common(1)[0][0], "weld"
    return "", "bos"


def colon_candidates(tables, meta: dict, method: str) -> collections.Counter:
    """How many trailing-colon values each step of the chain even SEES.

    The diff table alone cannot say whether a small change means the rule is narrow
    or means the corpus simply has few captions to cut. This census answers that:
    it counts the raw candidates, caught or not, at every step.
    """
    seen: collections.Counter = collections.Counter()
    extractor.item_is_bad = item_is_bad_legacy
    try:
        if extractor.extract_item_global(tables).rstrip().endswith(":"):
            seen["global"] += 1
        if squash(meta.get("description", "")).rstrip().endswith(":"):
            seen["description"] += 1
        welds = (extractor.extract_rt_welds(tables) if method == "RT"
                 else extractor.extract_welds(tables))
        seen["weld"] += sum(1 for w in welds
                            if squash(w.get("item", "")).rstrip().endswith(":"))
    finally:
        extractor.item_is_bad = _SHIPPED
    return seen


def cached_documents(input_dir: Path, cache_dir: Path):
    """``(name, tables)`` for every input document whose parse is already cached."""
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file() or path.suffix.casefold() not in (".docx", ".pdf"):
            continue
        if "_PRUNED" in path.relative_to(input_dir).parts or path.name.startswith("~$"):
            continue
        blob = cache_dir / f"{sha256(path)}.json"
        if not blob.is_file():
            continue
        try:
            tables = json.loads(blob.read_text(encoding="utf-8")).get("tables")
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(tables, str):
            tables = json.loads(tables)
        if tables:
            yield path.name, tables


# --------------------------------------------------------------------------
# Task 11-B2: the translation review sheet
# --------------------------------------------------------------------------

#: Values that are not inspected items at all but header tokens leaked out of the
#: source table. B1's trailing-colon rule cannot reach them — they carry no colon —
#: and ``_ITEM_BADSET`` was deliberately NOT widened in that task. They are listed
#: apart so the review never proposes a translation for a column heading.
_LEAKED_HEADERS = {"detailno", "detail no", "qty", "s/n", "item", "no"}

#: Confirmed misspellings of a term the dictionary ALREADY carries correctly. The
#: wrong form must never be added to az.json: a dictionary entry would make the typo
#: render cleanly and the source would never be fixed.
_CONFIRMED_TYPOS = {
    "Sructural weld": "Structural weld",
}

#: Proposed Azerbaijani renderings — SUGGESTIONS, not decisions. Every one of these
#: reaches az.json only through the operator column of the generated sheet. Only
#: recurring, genuinely translatable terms are proposed; identifiers and one-off
#: descriptions are left for the operator.
_PROPOSED = {
    "pipe to flange": "Boru–flans birləşməsi",
    "pipe to elbow": "Boru–dirsək birləşməsi",
    "pipe to tee": "Boru–troynik birləşməsi",
    "pipe to cap": "Boru–qapaq birləşməsi",
    "pipe to pipe cap": "Boru–boru qapağı birləşməsi",
    "pipe to reducer": "Boru–reduksiya birləşməsi",
    "reduction to pipe": "Reduksiya–boru birləşməsi",
    "tee to pipe": "Troynik–boru birləşməsi",
    "tee to flange": "Troynik–flans birləşməsi",
    "tee to reducer": "Troynik–reduksiya birləşməsi",
    "elbow to reducer": "Dirsək–reduksiya birləşməsi",
    "flange to adapter": "Flans–adapter birləşməsi",
    "adapter to pipe": "Adapter–boru birləşməsi",
    "plate to deck": "Təbəqə–göyərtə birləşməsi",
    "plate to beam": "Təbəqə–tir birləşməsi",
    "piping weld": "Boru kəməri qaynağı",
    "base metal": "Əsas metal",
    "welding area": "Qaynaq sahəsi",
    "test area": "Sınaq sahəsi",
    "spool": "Spul (boru qovşağı)",
    "utm spools": "UTM spulları",
    "flange": "Flans",
    "structure": "Konstruksiya",
    "grating panels": "Barmaqlıq panelləri",
    "reception line": "Qəbul xətti",
    "drainage line": "Drenaj xətti",
    "output line": "Çıxış xətti",
    "tank filling line": "Çən doldurma xətti",
    "nozzle 2": "Ştuser 2",
    "tank 2": "Çən 2",
    "2” pipe": "2” boru",
    "4 padeyes": "4 ədəd padey",
    "mud bucket arm": "Mud Bucket qolu",
    "spider assembly": "Spider yığımı",
    "male stab (5”)": "Erkək stab (5”)",
    "spool (5”)": "Spul (5”)",
    "gooseneck, swivel": "Qazboynu, fırlanğıc",
    "mud gas separator": "Gil məhlulu–qaz separatoru",
    "sdln work shop": "SDLN emalatxanası",
    "sdl n work shop": "SDLN emalatxanası",
    "sdl nobel work shop": "SDLN emalatxanası",
    "structural weld for uboc/neptun modification":
        "UBOC/NEPTUN modifikasiyası üçün konstruktiv qaynaq",
    "structural weld for uboc/neptun modification (ctud)":
        "UBOC/NEPTUN modifikasiyası üçün konstruktiv qaynaq (CTUD)",
    "structural steel welds for lifeboat service yard superstructure":
        "Xilasedici qayıq meydançasının üst konstruksiyasının polad qaynaqları",
    "south ro unit hp pump discharge spool":
        "Cənub RO qurğusunun YT nasosunun boşaltma spulu",
    "dt-v30120 finger slug catcher": "DT-V30120 barmaqlı sluq tutucu",
    "wqt": "Qaynaqçı ixtisas sınağı (WQT)",
}

#: Numbered items the corpus produces in a family rather than one at a time
#: ("Pipe 1" ... "Pipe 8"). Proposing each separately would be eight near-identical
#: dictionary lines; the pattern proposes the whole family at once, and the operator
#: still approves each row.
_NUMBERED = {
    "pipe": "Boru",
    "tank": "Çən",
    "nozzle": "Ştuser",
    "spool": "Spul",
}
_NUMBERED_RE = re.compile(r"^([A-Za-z]+)\s+(\d+)$")


def propose(value: str) -> str:
    """The suggested Azerbaijani rendering for a raw value, or ``""``."""
    key = value.strip().casefold()
    if key in _PROPOSED:
        return _PROPOSED[key]
    m = _NUMBERED_RE.match(value.strip())
    if m and m.group(1).casefold() in _NUMBERED:
        return f"{_NUMBERED[m.group(1).casefold()]} {m.group(2)}"
    return ""


#: An all-capital word of 2-6 letters with no spaces: WQT, CTUD, PWHT. Kept in its own
#: section because an acronym is expanded, not translated, and the expansion has to be
#: confirmed before it can be written down.
_ACRONYM = re.compile(r"^[A-Z]{2,6}$")

#: Azerbaijani letters, used to tell a source value that is ALREADY Azerbaijani
#: ("Radar meydançası") from one awaiting translation.
_AZ_LETTERS = set("əçğıöşüƏÇĞİÖŞÜ")


def is_identifier(value: str) -> bool:
    """True when the value is a job/spool/heat/serial number rather than a term.

    Three signals, each measured against the corpus: an ``S/N`` marker or an embedded
    newline (the cell swallowed a serial block), an alphanumeric code that starts with
    at most a few letters and then runs into digits (``15E441-03-B``, ``0179-01-A``),
    or simply a value that is a quarter digits or more. Identifiers are reported so
    the operator can SEE them, and marked "tərcümə olunmur" — translating a drawing
    number would make the sheet disagree with the drawing.
    """
    if "S/N" in value or "\n" in value:
        return True
    if re.fullmatch(r"[A-Za-z]{0,4}[-/ ]?\d[\w\-/.”’“ ():]*", value) \
            and sum(c.isdigit() for c in value) >= 2:
        return True
    return sum(c.isdigit() for c in value) / max(len(value), 1) >= 0.25


def classify(value: str) -> str:
    """Which section of the review a raw value belongs in."""
    if value.strip().casefold() in _LEAKED_HEADERS:
        return "header"
    if value in _CONFIRMED_TYPOS:
        return "typo"
    if _ACRONYM.fullmatch(value.strip()):
        return "acronym"
    if is_identifier(value):
        return "identifier"
    return "term"


def near_misses(values, dictionary) -> list[tuple[str, str]]:
    """``(value, closest dictionary key)`` pairs close enough to be worth a look.

    A suspicion list, not a verdict: ``Tee to pipe`` is close to ``plate to pipe`` and
    is nonetheless a real, distinct term. Only the entries in :data:`_CONFIRMED_TYPOS`
    are asserted to be misspellings.
    """
    keys = list(dictionary)
    out = []
    for value in values:
        hit = difflib.get_close_matches(value.casefold(), keys, n=1, cutoff=0.82)
        if hit and hit[0] != value.casefold():
            out.append((value, hit[0]))
    return out


def write_translation_review(values: collections.Counter,
                             clients: dict, dictionary: dict,
                             out_dir: Path, today: str) -> Path:
    """Write ``item_translation_review_<date>.md`` — the B2 proposal sheet."""
    unknown = {v: n for v, n in values.items()
               if v and dictionary.get(v.strip().lower()) is None}
    buckets: dict[str, list[str]] = collections.defaultdict(list)
    for value in unknown:
        buckets[classify(value)].append(value)

    def rows(names: list[str]) -> list[str]:
        out = []
        for value in sorted(names, key=lambda v: (-unknown[v], v.casefold())):
            who = ", ".join(c for c, _ in
                            collections.Counter(clients[value]).most_common(3))
            proposal = propose(value)
            if not proposal and set(value) & _AZ_LETTERS:
                proposal = "*(mənbə onsuz da Azərbaycan dilindədir)*"
            shown = value.replace("\n", " / ").replace("|", "\\|")
            out.append(f"| `{shown}` | {unknown[value]} | {who} | {proposal} |  |")
        return out

    head = ["| XAM dəyər | say | müştəri | təklif olunan qarşılıq | **OPERATOR DÜZƏLİŞİ** |",
            "|---|--:|---|---|---|"]

    repeated = [v for v in buckets["term"] if unknown[v] >= 2]
    oneoff = [v for v in buckets["term"] if unknown[v] == 1]

    lines = [
        f"# İtem/Detal — tərcümə icmalı — {today}",
        "",
        "Tapşırıq 11-B2. **`translations/az.json` bu faylla dəyişmir.** Bu, təklif "
        "vərəqidir: sətir lüğətə yalnız **OPERATOR DÜZƏLİŞİ** sütunu doldurulduqdan "
        "sonra düşür. Lüğət düz `{English: Azerbaijani}` cədvəlidir və axtarış tam "
        "uyğunluqla, reqistrdən asılı olmadan aparılır (`translator.py:17-22`), ona "
        "görə `Pipe to flange` və `Pipe to Flange` **bir** sətirlə örtülür.",
        "",
        "Tapılmayan dəyər sənədi pozmur — `translator.term` onu olduğu kimi buraxır "
        "(`translator.py:40-42`), yəni tərcüməsiz dəyər sadəcə ingiliscə qalır.",
        "",
        f"- lüğətdə **{len(dictionary)}** sətir",
        f"- korpusun İtem/Detal dəyərləri: **{len(values)}** fərqli, "
        f"**{sum(values.values())}** sənəddə",
        f"- lüğətin örtmədiyi: **{len(unknown)}** fərqli dəyər, "
        f"**{sum(unknown.values())}** sənəddə",
        "",
        "## 1. Təkrarlanan terminlər (say ≥ 2) — lüğətə namizədlər",
        "",
        f"{len(repeated)} dəyər.",
        "",
        *head, *rows(repeated),
        "",
        "## 2. Birdəfəlik təsvirlər (say = 1)",
        "",
        f"{len(oneoff)} dəyər. Bunlar bir sənədin öz təsviridir; lüğətə salmaq onu "
        "şişirdir və növbəti sənəddə heç nə qazandırmır. Təklif verilmir — operator "
        "lazım bildiyini seçir.",
        "",
        *head, *rows(oneoff),
        "",
        "## 3. İdentifikatorlar — TƏRCÜMƏ OLUNMUR",
        "",
        f"{len(buckets['identifier'])} dəyər: iş/spul/çertyoj/əritmə nömrələri və "
        "seriya nömrələri. Bunları tərcümə etmək vərəqi çertyojla ziddiyyətə salar. "
        "Siyahı yalnız görünürlük üçündür — təklif sütunu qəsdən boşdur.",
        "",
        *head, *rows(buckets["identifier"]),
        "",
        "## 4. Akronimlər",
        "",
        "Akronim tərcümə olunmur, **açılır** — açılış isə təsdiq tələb edir.",
        "",
        *head, *rows(buckets["acronym"]),
        "",
        "## 5. Yazı səhvləri",
        "",
        "**Səhv forma lüğətə SALINMIR.** Lüğətə yazılsa, səhv təmiz render olunar və "
        "mənbə heç vaxt düzəldilməz — düzəliş mənbə sənəddə aparılmalıdır.",
        "",
        "| XAM dəyər | say | lüğətdəki düzgün forma | qərar |",
        "|---|--:|---|---|",
    ]
    for wrong, right in sorted(_CONFIRMED_TYPOS.items()):
        n = unknown.get(wrong, 0)
        lines.append(f"| `{wrong}` | {n} | `{right}` -> "
                     f"`{dictionary.get(right.lower(), '—')}` | mənbə faylda düzəldilir |")
    lines += [
        "",
        "### Yoxlanmalı oxşarlıqlar",
        "",
        "Lüğət açarına yaxın, amma təsdiqlənməmiş dəyərlər. Bu siyahı **şübhədir, "
        "hökm deyil** — `Tee to pipe` `plate to pipe`-a yaxındır və buna baxmayaraq "
        "ayrıca, həqiqi termindir.",
        "",
        "| XAM dəyər | say | ən yaxın lüğət açarı |",
        "|---|--:|---|",
    ]
    for value, key in sorted(near_misses(unknown, dictionary),
                             key=lambda x: -unknown[x[0]]):
        if value in _CONFIRMED_TYPOS:
            continue
        lines.append(f"| `{value}` | {unknown[value]} | `{key}` |")

    lines += [
        "",
        "## 6. Sızmış başlıq tokenləri — termin DEYİL",
        "",
        "Bunlar yoxlanan detal deyil, mənbə cədvəlinin sütun başlığıdır. B1-in iki "
        "nöqtə qaydası onlara çatmır (iki nöqtə daşımırlar) və `_ITEM_BADSET` həmin "
        "tapşırıqda qəsdən genişləndirilmədi. Tərcümə təklif olunmur — bunların yeri "
        "lüğət yox, rədd siyahısıdır; bu, ayrıca operator qərarıdır.",
        "",
        *head, *rows(buckets["header"]),
        "",
    ]

    out = out_dir / f"item_translation_review_{today}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input-dir", default=str(_ROOT / "input"))
    ap.add_argument("--cache-dir", default=str(_ROOT / ".parse_cache"))
    ap.add_argument("--output-dir", default=str(_ROOT / "output"))
    ap.add_argument("--max-changed", type=int, default=30)
    args = ap.parse_args(argv)

    settings = config.load_settings(_ROOT / "config" / "settings.yaml")
    today = _dt.date.today().isoformat()

    scanned = 0
    changed: list[dict] = []
    census: collections.Counter = collections.Counter()
    # B2 collects from the SAME replay: the shipped rule's value, its count, and which
    # clients produce it. Re-walking the cache a second time would only risk the two
    # passes disagreeing about what the item column holds.
    items: collections.Counter = collections.Counter()
    item_clients: dict = collections.defaultdict(collections.Counter)
    for name, tables in cached_documents(Path(args.input_dir), Path(args.cache_dir)):
        scanned += 1
        meta = extractor.extract_meta(tables)
        method = detect_method(squash(meta.get("report_no", "")) or name, settings)

        extractor.item_is_bad = item_is_bad_legacy
        before, src_before = resolve_item(tables, meta, method)
        extractor.item_is_bad = item_is_bad_with_colon_rule
        after, src_after = resolve_item(tables, meta, method)
        extractor.item_is_bad = _SHIPPED

        census.update(colon_candidates(tables, meta, method))

        shipped, _ = resolve_item(tables, meta, method)
        if shipped:
            items[shipped] += 1
            item_clients[shipped][squash(meta.get("client", "")) or "?"] += 1

        if before != after:
            changed.append({"name": name, "before": before, "after": after,
                            "src_before": src_before, "src_after": src_after})

    out = Path(args.output_dir) / f"item_detail_diff_{today}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# İtem/Detal — iki nöqtə qaydasının təsiri — {today}",
        "",
        "Tapşırıq 11-B1. Qayda: `text.rstrip().endswith(\":\")` olan dəyər **rədd**",
        "olunur — o, bu sətrin dəyəri yox, **növbəti başlıqdır**. Aşağıdakı cədvəl",
        "aqreqatorun üç pilləli zəncirini (`global` → `description` → `weld`) hər",
        "sənəd üçün iki dəfə işlədərək alınıb.",
        "",
        f"- skan olunan sənəd: **{scanned}**",
        f"- dəyişən sətir: **{len(changed)}**",
        f"- dəyişməyən: **{scanned - len(changed)}**",
        "",
        "| # | fayl | KÖHNƏ dəyər | YENİ dəyər | mənbə (köhnə → yeni) |",
        "|--:|---|---|---|---|",
    ]
    for i, row in enumerate(sorted(changed, key=lambda r: r["name"]), 1):
        lines.append(f"| {i} | `{row['name']}` | `{row['before']}` | `{row['after']}` "
                     f"| {row['src_before']} → {row['src_after']} |")

    lines += ["", "## İki nöqtəli namizədlərin siyahıya alınması", "",
              "Qaydanın dar olması ilə korpusda kəsiləcək başlığın az olmasını",
              "ayırd etmək üçün: zəncirin hər pilləsinin **gördüyü** xam",
              "iki nöqtəli dəyərlərin sayı.", "",
              "| pillə | iki nöqtəli namizəd |", "|---|--:|"]
    lines += [f"| {step} | {census.get(step, 0)} |"
              for step in ("global", "description", "weld")]

    tally = collections.Counter(r["before"] for r in changed)
    lines += ["", "## Silinən dəyərlər (say üzrə)", "",
              "| XAM dəyər | say |", "|---|--:|"]
    lines += [f"| `{value}` | {count} |" for value, count in tally.most_common()]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    review = write_translation_review(items, item_clients,
                                      load_dictionary(_ROOT / "translations" / "az.json"),
                                      out.parent, today)

    print(f"[item-detail] {scanned} document(s) replayed, "
          f"{len(changed)} row(s) changed -> {out}")
    print(f"[item-detail] translation review -> {review}")
    if len(changed) > args.max_changed:
        print(f"[item-detail] STOP: {len(changed)} > --max-changed {args.max_changed}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
