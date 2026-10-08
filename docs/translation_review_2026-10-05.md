# İtem / Detal translation review — 2026-10-05

**Applied R4-D (2026-10-06).** The operator approved this review with the final scope: only values that render in the İtem / Detal column are translated. Every row of table 1 and the first three rows of table 5 are now in `translations/az.json` (70 added, 3 changed). Removed from this file because they are not İtem values: the old section 4 (`—`, `S/N`, `Qty`, `DetailNo`, `Number of holes`, `N/A`: header labels, placeholders, the renderer blank marker), `UTM` (a method token; the Üsul column is never translated), and `Weld ID` / `WDR ID` (labels with no render call in `src/`; unchanged in `az.json`, value still `Qaynaqçı / Tikiş İD`). Table 3 identifiers stay out of `az.json`.

**Updated R3 (2026-10-05), operator decision S2:** "weld" is **"qaynaq"** everywhere, never "tikiş". Every proposal below follows it, and section 5 lists the existing `az.json` entries that must change with it.

Source: a read-only replay of the current corpus with the live settings — the same `split_display_rows` lines `pdf_renderer.py` draws (İtem cell = `translator.term(item_detail)`, `pdf_renderer.py:358`). All 130 compiled documents were replayed; the set matches `output/` exactly. `az.json` lookup is exact, case-insensitive, after trimming (`translator.py:34-38`); a value with no entry prints in English, unmarked (`term`, not `controlled`, so no `[AZ?]` marker appears on İtem).

## Counts

- İtem values printed on PDF lines: **120** distinct; with no `az.json` entry: **108**.
- Of those, English terms to translate (table 1): **71** unique terms (dictionary rows) (51 high, 20 low confidence), **177** PDF lines, **64** documents.
- Already Azerbaijani in the source (table 2): 20. Identifiers kept as is (table 3): 10. Not an item / extraction artefacts (table 4): 6.
- 2026+ uploadable documents (approved client, month ≥ 2026-01): **36**; with at least one English İtem line: **14** — BS_APR_2026, BS_JUN_2026, BS_MAY_2026, BS_SEP_2026, KHF_AUG_2026, KHF_FEB_2026, KHF_JAN_2026, KHF_JUL_2026, KHF_MAR_2026, NOV_JAN_2026, UBOC_JUL_2026, UBOC_JUN_2026, UBOC_OCT_2026, UBOC_SEP_2026.
- Not on any PDF line but in sidecar `item_name` (hidden by `range_item: dominant`): 278 untranslated values, 426 sidecar rows. Not proposed here (scope: what reaches a PDF). The operator's earlier examples `Welding of the basket arms` and `Pipe to pipe` are in this group today; `Pipe to pipe` already has an entry.

## 1. English → Azerbaijani (proposed)

| English source | count (rows) | documents | proposed Azerbaijani | confidence | note |
|---|--:|---|---|---|---|
| `SDL N WORK SHOP` | 14 | SDLN_NOV_2025, SDLN_OCT_2025, SDLN_SEP_2025 | SDLN emalatxanası | high | same workshop as `SDLN WORK SHOP`; spacing differs in the source |
| `SDLN WORK SHOP` | 13 | SDLN_NOV_2025, SDLN_OCT_2025, SDLN_SEP_2025 | SDLN emalatxanası | high |  |
| `Pipe to flange` | 11 | UBOC_AUG_2025, UBOC_SEP_2026 | Boru-flans | high | style of the existing `Flange to pipe` → `Flans-boru` |
| `Structural weld for UBOC/NEPTUN Modification` | 10 | KHF_AUG_2025, KHF_JUL_2025, KHF_JUN_2025, KHF_SEP_2025 | UBOC/NEPTUN modifikasiyası üçün konstruktiv qaynaq | high | S2; matches `Structural weld` → `Konstruktiv qaynaq` (section 5) |
| `Piping weld` | 9 | KHE_APR_2026, KHE_AUG_2026, KHE_JUN_2026, KHE_MAY_2026 (+3) | Boru kəməri qaynağı | high | S2: operator's term |
| `GOOSENECK, SWIVEL` | 8 | NOV_OCT_2025 | Qazboynu, vertlyuq (GOOSENECK, SWIVEL) | low | drilling equipment; local jargon varies |
| `WQT` | 8 | BS_JUN_2026, BS_MAY_2026, KHF_AUG_2025, KHF_JUL_2025 (+3) | Qaynaqçının ixtisas sınağı (WQT) | high | operator's example |
| `DT-V30120 Finger Slug Catcher` | 6 | UBOC_FEB_2025, UBOC_JAN_2025, UBOC_MAY_2025 | DT-V30120 barmaqvari tıxac tutucu (Finger Slug Catcher) | low | no settled Azerbaijani term known |
| `SPOOL (5”)` | 5 | NOV_JAN_2026, NOV_OCT_2025 | Spul (boru seksiyası) (5”) | high | operator's `Spool` example |
| `Spool` | 4 | KHE_AUG_2026, KHE_DEC_2025, KHE_MAY_2026, KHF_MAR_2026 | Spul (boru seksiyası) | high | operator's example |
| `UTM Spools` | 4 | NOV_OCT_2025 | UTM spulları (boru seksiyaları) | high |  |
| `C100B80X939 crane (North side)` | 3 | UBOC_APR_2025, UBOC_MAR_2025 | C100B80X939 kranı (şimal tərəf) | high | crane ID kept |
| `Pipe 1` | 3 | AZF_DEC_2024, AZF_JAN_2025, AZF_NOV_2024 | Boru 1 | high | az.json: `Pipe` → `Boru` |
| `Pipe to elbow` | 3 | UBOC_SEP_2026 | Boru-dirsək | high | style of `Elbow to pipe` → `Dirsək-boru` |
| `Reception line` | 3 | UBOC_FEB_2025, UBOC_JAN_2025, UBOC_MAR_2025 | Qəbul xətti | high |  |
| `YGI-8000 MUD GAS SEPARATOR` | 3 | UBOC_APR_2025, UBOC_MAR_2025 | YGI-8000 qazma məhlulu-qaz separatoru | low | mud-gas separator; term not settled |
| `16” EA HP LINE` | 2 | KHE_OCT_2025 | 16” EA yüksək təzyiq xətti | low | meaning of `EA` UNKNOWN / NEEDS VERIFICATION |
| `3”x160 atm 900 Class` | 2 | UBOC_JUN_2026 | 3”x160 atm 900 sinif | high | flange pressure class |
| `4 padeyes` | 2 | BS_APR_2026, BS_SEP_2026 | 4 qaldırıcı qulaq (Padeyes) | high | az.json: `Padeyes` → `Qaldırıcı qulaqlar (Padeyes)` |
| `Flange to flange` | 2 | UBOC_SEP_2026 | Flans-flans | high |  |
| `Heat Exchanger 300GZAZ303093-T13` | 2 | GEMZA_AUG_2025 | İstilik dəyişdiricisi 300GZAZ303093-T13 | high | see T73 |
| `Heat Exchanger 300GZAZ303093-T14` | 2 | GEMZA_JUL_2025 | İstilik dəyişdiricisi 300GZAZ303093-T14 | high | see T73 |
| `Heat Exchanger 300GZAZ303093-T73` | 2 | GEMZA_NOV_2024 | İstilik dəyişdiricisi 300GZAZ303093-T73 | high | az.json is exact-match: each tag number needs its own entry (7 here) |
| `Heat Exchanger 300GZAZ303093-T9 (3)` | 2 | GEMZA_JUN_2025 | İstilik dəyişdiricisi 300GZAZ303093-T9 (3) | high | see T73 |
| `MALE STAB (5”)` | 2 | NOV_OCT_2025 | Stab birləşməsi, ata hissə (5”) | low | male/female connector wording is the operator's call |
| `Plate to deck` | 2 | KHF_AUG_2025 | Lövhə-göyərtə | high |  |
| `SDL NOBEL WORK SHOP` | 2 | SDLN_OCT_2025, SDLN_SEP_2025 | SDL Nobel emalatxanası | high | proper name kept |
| `South RO Unit HP Pump discharge spool` | 2 | KHF_FEB_2024, KHF_FEB_2025 | Cənub RO qurğusu yüksək təzyiqli nasosunun vurma spulu | low | RO = reverse osmosis (tərs osmos) |
| `Spider Assembly` | 2 | NOV_MAY_2025 | Spayder qovşağı (Spider Assembly) | low | drilling slip spider; term not settled |
| `Structural weld for UBOC/NEPTUN Modification (CTUD)` | 2 | KHF_OCT_2025, KHF_SEP_2025 | UBOC/NEPTUN modifikasiyası üçün konstruktiv qaynaq (CTUD) | high | CTUD kept as written |
| `Accumulator 5000PSI` | 1 | NOV_JAN_2026 | Akkumulyator 5000 PSI | high |  |
| `Base metal` | 1 | UBOC_JUN_2025 | Əsas metal | high |  |
| `Beam to plate Assembly 1` | 1 | KHF_AUG_2025 | Tir-lövhə yığımı 1 | high |  |
| `Boat repair welds` | 1 | KHF_JUL_2026 | Qayıq təmiri qaynaqları | high | S2 |
| `Cutting Diverter` | 1 | KHF_MAR_2025 | Şlam yönləndiricisi (Cutting Diverter) | low | drill-cuttings diverter |
| `Drainage line` | 1 | UBOC_DEC_2025 | Drenaj xətti | high |  |
| `Fire wall` | 1 | UBOC_NOV_2024 | Yanğın divarı | high |  |
| `Flange to hose end` | 1 | KHF_FEB_2026 | Flans-şlanq ucu | high |  |
| `Heat Exchanger 300GZAZ303093-T15` | 1 | GEMZA_DEC_2024 | İstilik dəyişdiricisi 300GZAZ303093-T15 | high | see T73 |
| `Heat Exchanger 300GZAZ303093-T79 (2)` | 1 | GEMZA_FEB_2025 | İstilik dəyişdiricisi 300GZAZ303093-T79 (2) | high | see T73 |
| `Heat Exchanger 300GZAZ303093-T86` | 1 | GEMZA_DEC_2024 | İstilik dəyişdiricisi 300GZAZ303093-T86 | high | see T73 |
| `Heat Exchanger 300GZAZ303093-T9 (1)` | 1 | GEMZA_APR_2025 | İstilik dəyişdiricisi 300GZAZ303093-T9 (1) | high | see T73 |
| `Heat Exchanger 300GZAZ303093-T9 (2)` | 1 | GEMZA_MAY_2025 | İstilik dəyişdiricisi 300GZAZ303093-T9 (2) | high | see T73 |
| `ILF DOOR BODY D NOV-2281614` | 1 | NOV_AUG_2025 | ILF qapı gövdəsi D NOV-2281614 | low | ILF / D meaning UNKNOWN / NEEDS VERIFICATION |
| `MPD Riser Crossover⏎(Lower adapter)` | 1 | KHF_NOV_2024 | MPD rayzer keçid hissəsi (aşağı adapter) | low | source carries a line break; az.json needs this exact key too |
| `MPD Riser Crossover (Lower adapter)` | 1 | KHF_NOV_2024 | MPD rayzer keçid hissəsi (aşağı adapter) | low | MPD = managed pressure drilling |
| `Modification of screen` | 1 | KHF_JAN_2026 | Ekranın modifikasiyası | low | screen = shield or sieve? UNKNOWN / NEEDS VERIFICATION |
| `Mud Bucket Adapter Bracket` | 1 | NOV_AUG_2025 | Palçıq vedrəsi adapterinin kronşteyni | low |  |
| `Output line` | 1 | UBOC_FEB_2025 | Çıxış xətti | high |  |
| `Padeye plate` | 1 | KHF_JAN_2025 | Qaldırıcı qulaq lövhəsi | high |  |
| `Pins` | 1 | UBOC_OCT_2026 | Pinlər (ştiftlər) | low | pin = dowel or threaded pin end? UNKNOWN / NEEDS VERIFICATION |
| `Pipe 3` | 1 | AZF_APR_2025 | Boru 3 | high |  |
| `Pipe 6”` | 1 | UBOC_JUL_2026 | Boru 6” | high |  |
| `Pipe line` | 1 | BS_DEC_2024 | Boru xətti | high |  |
| `Pipe spool` | 1 | UBOC_APR_2024 | Boru spulu (boru seksiyası) | high |  |
| `Reduction to Pipe` | 1 | UBOC_JUL_2025 | Reduksiya-boru | high | same az.json row as `Reduction to pipe` |
| `Reduction to pipe` | 1 | UBOC_AUG_2025 | Reduksiya-boru | high | one entry also covers `Reduction to Pipe` (lookup ignores case) |
| `SBOP Lower Housing` | 1 | NOV_OCT_2025 | SBOP aşağı korpusu | low | SBOP expansion UNKNOWN / NEEDS VERIFICATION |
| `SPOOL (6”)` | 1 | NOV_OCT_2025 | Spul (boru seksiyası) (6”) | high |  |
| `STAB FEMALE (6”)` | 1 | NOV_OCT_2025 | Stab birləşməsi, ana hissə (6”) | low | see MALE STAB |
| `STAB, FEMALE (6”)` | 1 | NOV_OCT_2025 | Stab birləşməsi, ana hissə (6”) | low | comma variant of the line above; separate entry needed |
| `Separators` | 1 | UBOC_OCT_2025 | Separatorlar | high |  |
| `Spool 1` | 1 | KHF_NOV_2024 | Spul 1 | high |  |
| `Spool-1; Weld-SW1` | 1 | KHF_APR_2025 | Spul-1; Qaynaq-SW1 | high | SW1 is an identifier |
| `Sructural weld` | 1 | KHF_SEP_2025 | Konstruktiv qaynaq | high | typo is in the source; key must keep the typo |
| `Structural weld for UBOC/NEPTUN Modification (HULL)` | 1 | KHF_SEP_2025 | UBOC/NEPTUN modifikasiyası üçün konstruktiv qaynaq (korpus) | low | HULL = vessel hull; `korpus` vs `gövdə` is the operator's call |
| `Tank 2` | 1 | UBOC_DEC_2024 | Çən 2 | high |  |
| `Tee to pipe` | 1 | UBOC_SEP_2026 | Troynik-boru | high |  |
| `Test area` | 1 | UBOC_DEC_2025 | Sınaq sahəsi | high |  |
| `Welding area` | 1 | UBOC_JUN_2026 | Qaynaq sahəsi | high |  |
| `plate to UB` | 1 | KHF_SEP_2025 | Lövhə-UB | low | `UB` UNKNOWN / NEEDS VERIFICATION (universal beam?) |

## 2. Already Azerbaijani — no entry needed

| source | count (rows) | documents |
|---|--:|---|
| `M1 modulunun rabitesi` | 4 | UBOC_JAN_2025, UBOC_NOV_2024 |
| `DB-2 (Diafraqma D1)` | 3 | UBOC_AUG_2025, UBOC_JUL_2025, UBOC_SEP_2025 |
| `Yeni dizel qəbul xətti` | 2 | UBOC_OCT_2025 |
| `Keyson xətti` | 1 | UBOC_MAY_2025 |
| `Gənub yük kranı (C100B80X940)` | 1 | UBOC_OCT_2025 |
| `Mədən sahəsində 1”-lik və 3”-lik su çiləmə borusu` | 1 | UBOC_SEP_2025 |
| `M1 modulunun rabitesi (II&III)` | 1 | UBOC_JAN_2025 |
| `M4 modulunda F3 fermasının gücləndirilməsi` | 1 | UBOC_JUN_2026 |
| `Şimal kranı C100B80X939` | 1 | UBOC_MAY_2026 |
| `KEQ12 kranı` | 1 | UBOC_DEC_2025 |
| `Hava çəni 2m3` | 1 | UBOC_JUL_2025 |
| `AYS sistemi` | 1 | UBOC_FEB_2026 |
| `Mədən sahəsində S1 və S2 6" maye xətti` | 1 | UBOC_SEP_2025 |
| `Metal konstruksiya` | 1 | UBOC_AUG_2026 |
| `Qaz seperatoru 1` | 1 | UBOC_SEP_2026 |
| `Rabitə borusu I;II` | 1 | UBOC_FEB_2025 |
| `Radar meydançası` | 1 | UBOC_JUN_2025 |
| `Lafet qülləsi` | 1 | UBOC_APR_2025 |
| `Çən 1 (karkas)` | 1 | UBOC_NOV_2024 |
| `Şveller-bucaq profil birləşmələri` | 1 | UBOC_AUG_2026 |

## 3. Identifiers — keep as is

| source | count (rows) | documents | note |
|---|--:|---|---|
| `DB-2` | 19 | UBOC_AUG_2025, UBOC_DEC_2025, UBOC_FEB_2026, UBOC_JAN_2026 (+3) |  |
| `M1-M1A` | 8 | UBOC_FEB_2026, UBOC_MAY_2026 |  |
| `M1` | 4 | UBOC_MAY_2026 |  |
| `DB1` | 1 | UBOC_JUL_2026 |  |
| `DB2` | 1 | UBOC_AUG_2026 |  |
| `M1-D` | 1 | UBOC_NOV_2024 |  |
| `10E-389-01-A` | 1 | SDLN_JAN_2025 |  |
| `FC-07D047-01` | 1 | SDLN_OCT_2025 |  |
| `ST-DTL-014832-D-002-001 C01` | 1 | SDLN_JUN_2026 |  |
| `24’’ XLF Box:HT:2-858765-6 / 205379 / 1175561 24” XLF PIN:HT:858767-18/205382 / 1175562` | 1 | SDLN_SEP_2025 | heat numbers; `Box`/`PIN` are thread-end names, kept |

## Notes for the operator

- One dictionary row per exact string. `Reduction to pipe` / `Reduction to Pipe` share one row (case is ignored); `STAB FEMALE` / `STAB, FEMALE`, the two `MPD Riser Crossover` spellings and the nine `Heat Exchanger …` tags each need their own row. A prefix rule would be a code change.
- S2 settled the weld term: `qaynaq`. The proposals above and section 5 apply it.
- Adding entries changes already delivered PDFs on the next run (the dictionary's mtime re-renders every group; `main.py` `_config_stamp`). The sidecar `item_name` changes with it.

## 5. Existing `az.json` entries that render "weld" as "tikiş" (S2)

Every entry whose English key contains "weld" and whose value contains "tikiş", plus the one entry with the same value under another key. Old → new; **not applied** (the operator approves the full table first). "2026+ rows" = sidecar rows (`item_name`) in 2026+ documents that carry the old value today, measured on the sidecars of 2026-10-05 after R3-D.

| English key | old value | new value | 2026+ rows | 2026+ documents |
|---|---|---|--:|---|
| `Structural weld` | Konstruktiv tikiş | Konstruktiv qaynaq | 51 | KHE_JAN/FEB/MAR/APR/MAY_2026, KHF_JAN/FEB/MAR/APR/JUN/JUL/SEP_2026, UBOC_MAY_2026 (13) |
| `Structural welds` | Konstruktiv tikişlər | Konstruktiv qaynaqlar | 10 | KHF_FEB/MAR/JUN/JUL/SEP_2026 (5) |
| `Weld` | Tikiş | Qaynaq | 1 | KHF_JUN_2026 |

Total: **62 sidecar rows in 2026+ documents**. The 51 includes `KF-DP-26-008`, whose İtem changed from `Qty` to `Structural weld` in R3-D.

- `Weld ID` and `WDR ID` share one value. They are table labels, not İtem values; a grep of `src/` and `uploader.py` finds no `term("Weld ID")` / `term("WDR ID")` call, so their render site is UNKNOWN / NEEDS VERIFICATION. Changing only one would leave the two labels different; both are listed.
- `Unretested Rejected Welds` → `Təkrar yoxlanılmamış yararsız qaynaqlar` already uses `qaynaq`: no change.
- No other `az.json` value contains "tikiş" (77 entries checked).
