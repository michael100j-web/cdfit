# Handoff: Zmenšení startovního kontextu (konektory a pluginy na claude.ai)

> Aktualizováno: 2026-11-20 · Složka: `C:\Users\micha\Documents\cdfit` · Větev: `claude-skill` @ `5a07976` (necommitnuté: `CLAUDE.md`, nový; bez souvislosti s tímto úkolem)
> Nová session: přečti celý soubor, ověř „Stav“ proti souborům a začni prvním bodem v „Další krok“.

## Cíl
Vypnout na claude.ai nepoužívané konektory a pluginy, aby každá session začínala s menším kontextem a Claude nesahal po nesouvisejících nástrojích. Hotovo je, když jsou 5 položek z „Další krok“ vypnuté a nová session ukazuje menší „MCP tools“ a „MCP server instructions“ v `get_usage`.

## Stav
**Hotovo a ověřeno**
- Skill `handoff` je ve skupině Fiala Lab MUNI jako v1, „Everyone · installed by default“. Ověřeno v admin stránce claude.ai 2026-11-18, lokální kopie je v koši.
- Globální `~/.claude/CLAUDE.md` je přepsaný (22 řádků) a projektový `CLAUDE.md` v cdfit vytvořený. Testovací příkazy v něm byly 2026-11-18 spuštěny a prošly.
- Výchozí stav kontextu (`get_usage`, 2026-11-18, session o 283 tisících tokenech): System tools 21 787, MCP tools 18 537, System prompt 11 100, Skills 9 959, MCP server instructions 3 883. Okno má 1 milion tokenů, kompakce startuje na 97 %.

**Hotovo s výhradou nebo neověřeno**
- Úspora po vypnutí je odhad, 5–20 tisíc tokenů. Část „MCP tools“ tvoří nástroje samotné aplikace (prohlížeč, sessions, terminal), ty vypnout nejdou.

**Rozpracováno**
- 2026-11-20 vypnuto na claude.ai (Customize, sekce „Yours“ = osobní): Windsor.ai odpojen; pluginy Data, Productivity, Dataiku Headless odebrány (lze vrátit tlačítkem „Add“). Lokálně v `~/.claude/plugins/synced` zbyl jen bio-research.
- Bod 5 nejde na claude.ai: PubMed/Consensus v Bio Research jsou tytéž konektory jako samostatné (sdílený stav „Connected“). Zbývá jen per-projekt vypnutí v Claude Code (`/mcp` → `plugin:bio-research:pubmed`, `…:consensus`), čeká na rozhodnutí uživatele.
- `get_usage` v nové session ještě neověřen (týdenní limit 99 %). Session, která to dělala, startovala před změnou: MCP tools 17 342, MCP server instructions 3 883.

## Další krok
1. Ve vlastním Chromu (Claude in Chrome; vestavěný prohlížeč neumí všechno) otevři nastavení konektorů a pluginů na claude.ai a vypni:
   1. konektor **Windsor.ai**;
   2. plugin **data** (Amplitude, BigQuery, Hex, Definite);
   3. plugin **productivity** (Asana, Atlassian, ClickUp, Linear, Monday, Notion, Slack);
   4. **headless / Dataiku**;
   5. v pluginu **bio-research** jen jeho **Consensus** a **PubMed**. Samostatné konektory Consensus a PubMed nech zapnuté.

   Před každým vypnutím ověř na stránce, že jde o osobní nastavení, ne o nastavení celé organizace. Kdyby to bylo nastavení organizace, zeptej se uživatele.
2. Otevři novou session a zavolej `get_usage`. Porovnej kategorie s čísly v „Stav“.
3. Napiš uživateli krátce, co je vypnuté a kolik tokenů se ušetřilo.

## Rozhodnutí
- Udělat to v nové session, ne v té původní: krok tam stál asi 290 tisíc tokenů, v nové session asi 88 tisíc. Týdenní limit byl 2026-11-18 na 94 % (obnova pá 21. 11. v 9:00). Rozhodl Claude, uživatel souhlasil.
- Ponechat zbytek bio-research (ChEMBL, bioRxiv, Open Targets…) a všechny vlastní skilly. Rozhodl Claude, uživatel nic nenamítl.
- Lokální `~/.claude/skills/cdfit` a `chemdraw` zatím nemazat. Jsou novější než verze ve skupině (např. `cdfit_repr.py` je jen lokálně). Nejdřív nahrát nové verze skupině, to je samostatný úkol.

## Slepé uličky a pasti
- Chrome `file_upload` nahraje jen soubory ze složek session, jiné odmítne: „only files this session is allowed to read can be uploaded“. Obejití: zkopírovat soubor do scratchpadu session.
- Hook `block-habay` zablokuje Bash, kde se v textu objeví `z:` (třeba proměnná `as z:` v Pythonu). Stačí přejmenovat proměnnou.
- `py -I` nevidí pymupdf ani pytest (jsou v uživatelských site-packages), pro vlastní skripty používej `py`.

## Soubory
- `CLAUDE.md` — nový projektový CLAUDE.md, necommitnutý; uživatel se k commitu nevyjádřil.
- `HANDOFF-context-trim.md` — tato poznámka.

## Příkazy
```powershell
# Spotřeba tokenů tohoto týdne ze všech logů Claude Code (skript ve scratchpadu staré session; může zmizet)
py "C:\Users\micha\AppData\Local\Temp\claude\e5116e65c5ca8871\566d7f5a-f94e-4163-87a6-2a8fb95136fe\scratchpad\week_tokens.py" 2026-11-21T08:00:00
```

## Otevřené otázky
- Commitnout `CLAUDE.md` do `claude-skill`? Výchozí: necommitovat, dokud uživatel neřekne.
- Nahrát nové verze cdfit a chemdraw do skupiny a pak smazat lokální kopie? Samostatný úkol.

## Kontext mimo soubory
- Měření 2026-11-18: týden od 14. 11. 9:00 = 5 467 volání, 1,53 mld vstupních tokenů (97 % cache), 8,3 mil. výstupních, při 94 % týdenního limitu. Celý týden tedy ≈ 1,6 mld tokenů. Průměrné volání četlo 280 tisíc. Fable má samostatný týdenní limit a byl na 100 %.
- Uživatel připravuje pro kolegy prezentaci o kontextovém okně: přirovnání k pracovnímu stolu, 88 tisíc tokenů základu, „17 otázek, 98 přečtení stolu“. One-pager je v `C:\Users\micha\Documents\collagen_td\guides\Claude skill guide - Handoff.pdf`.
- Uživatel je vlastník organizace Fiala Lab MUNI. Skilly skupiny se nahrávají přes https://claude.ai/admin-settings/skills.
