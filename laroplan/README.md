# Läroplan Lgr22 – grundskolan åk 7–9 (SQLite)

`laroplan.db` innehåller Skolverkets kursplaner för **alla 27 ämnen i grundskolan**, avgränsat till årskurs 7–9, samt läroplanens del 1–3 (värdegrund, övergripande mål och riktlinjer). Texten är Skolverkets egen, hämtad från deras öppna [Syllabus API](https://www.skolverket.se/om-oss/oppna-data/api-for-laroplaner-kurs--och-amnesplaner-syllabus).

Databasen innehåller också frågorna till flashcardappen Plugga (mappen ovanför) (tabellerna `fraga`, `fraga_ci`, `tema`, `samling`). `bygg.py` bygger bara om läroplanstabellerna och rör aldrig frågorna.

Uppdatera när Skolverket ändrar något:

```sh
python3 bygg.py        # hämtar läroplanen på nytt och bygger om dess tabeller (bara standardbiblioteket)
```

## Tabeller

| Tabell | Innehåll |
|---|---|
| `amne` | Ett ämne per rad: kod, namn, beteckning (KE, MA …), version, SKOLFS, beskrivning och **syfte** |
| `amne_mal` | Ämnets långsiktiga mål (”förmågorna”) ur syftet, en per rad |
| `centralt_innehall` | **Centralt innehåll åk 7–9**, en punkt per rad, med rubriken (`omrade`) den står under |
| `centralt_innehall_block` | Samma sak som hela block (ren text + original-HTML) |
| `betygskriterier` | **Betygskriterier E, D, C, B, A i slutet av åk 9** |
| `laroplan_avsnitt` / `laroplan_underavsnitt` | Lgr22 del 1–4, uppdelat på rubriker |
| `sok` | Fritextsökning (FTS5) över allt ovan |
| `metadata` | Källa, version och hämtdatum |

`centralt_innehall.nyckel` (t.ex. `GRGRKEM01::7-9:5`) är stabil mellan ombyggnader och används för att koppla frågor till läroplanen.

Språkämnen med flera varianter (moderna språk, modersmål för minoritetsspråk, samiska, teckenspråk) har kolumnerna `variant` / `variant_namn`, t.ex. *språkval*, *skolans val*, *finska som förstaspråk*. För vanliga ämnen är de tomma.

Färdiga vyer: `v_oversikt`, `v_centralt_innehall`, `v_betygskriterier`.

## Exempel

```sh
sqlite3 -header -column laroplan.db "SELECT * FROM v_oversikt"
```

```sql
-- Centralt innehåll i kemi åk 7–9
SELECT omrade, text FROM v_centralt_innehall WHERE amne = 'Kemi';

-- Vad krävs för E respektive A i matematik?
SELECT betyg, text FROM v_betygskriterier WHERE amne = 'Matematik' AND betyg IN ('E','A');

-- Ämnets långsiktiga mål
SELECT m.text FROM amne_mal m JOIN amne a ON a.kod = m.amne_kod WHERE a.namn = 'Fysik';

-- Fritextsök i alla ämnen (prefix med *)
SELECT amne, del, rubrik, snippet(sok, 3, '[', ']', '…', 12) FROM sok WHERE sok MATCH 'klimat*';

-- Moderna språk inom språkval
SELECT variant_namn, omrade, text FROM v_centralt_innehall WHERE amne = 'Moderna språk' AND variant_namn = 'språkval';
```

Databasen kan också öppnas i t.ex. [DB Browser for SQLite](https://sqlitebrowser.org/) eller VS Code-tillägget *SQLite Viewer*.
