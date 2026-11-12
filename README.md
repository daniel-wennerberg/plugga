# Plugga

Flashcards för alla ämnen i grundskolan åk 7–9, kopplade till läroplanen Lgr22.
Frågorna ligger i samma SQLite-databas som läroplanen (`laroplan/laroplan.db`) och administreras i ett webbgränssnitt.

Fristående från kemiappen *Kolets kemi* (eget repo `kolets-kemi`). Inga filer, ingen databas och ingen localStorage-nyckel delas (`plugga-v1` här, `kolets-kemi-v1` där).

## Två sätt att använda appen

| | Adress | Innehåll |
|---|---|---|
| **Online** (GitHub Pages) | https://daniel-wennerberg.github.io/plugga/ | flashcards och läroplan, ingen admin. Uppdateras när man bygger om och pushar. |
| **Lokalt** | http://localhost:8090/ och http://localhost:8090/admin | allt, inklusive admin för att skriva och ändra frågor |

```sh
cd ~/claude/leon/plugga
python3 server.py                 # lokalt, med admin
python3 server.py --bygg-sida     # bygg om docs/ från databasen
git add -A && git commit -m "Nya frågor" && git push   # publicera
```

Lokalt fungerar flashcards även från mobil/surfplatta på samma nätverk: `http://<datorns-ip>:8090/`. Ändringar (skapa, ändra, ta bort, importera) tillåts bara från datorn där servern körs.

Markeringar (röd/gul/grön) sparas i webbläsarens localStorage, separat per webbläsare och adress.

## Innehåll

| Ämne | Fil i `seed/` | Frågor |
|---|---|---|
| Kemi – Kolets kemi | `kemi-kolets-kemi.json` | 189 (80 instuderingsfrågor + 109 ur Stella KEMI 7–9 s. 100–141) |
| Historia – Prov: Revolutioner förändrar världen | `historia-revolutioner.json` | 74 (amerikanska, franska och industriella revolutionen, analysmodell, KEPS, jämförelser) |

Läs in en fil: `python3 server.py --import seed/<fil>.json` (dubbletter hoppas över).

Nivåerna E/C/A är satta efter frågans formulering och **inte granskade** – filtrera på ”Ej granskade” i admin och bocka i *Granskad* när en fråga är kontrollerad.

## Admin

- **Frågor** – lista med sökning och filter (nivå, tema, samling, granskad, läroplanspunkt, dold). Klicka på en fråga för att redigera. Markera flera för att ändra nivå, tema, samling, koppling eller granskning på en gång. `⌘/Ctrl + Enter` sparar.
- **Läroplan & täckning** – ämnets mål, centralt innehåll åk 7–9 med antal frågor per nivå (orange = saknar frågor) och betygskriterierna för E, C och A. Härifrån kan man skriva en ny fråga kopplad direkt till en punkt.
- **Teman & samlingar** – teman är avsnitt inom ämnet (t.ex. *Alkoholer*), samlingar är var frågorna kommer ifrån (t.ex. ett läromedel eller ett prov). Byt namn, ändra ordning, ta bort.
- **Import/export** – JSON-fil per ämne, för säkerhetskopia eller för att dela frågor.

### Nivåer

| Nivå | Betygskriterium (Lgr22) | Typ av fråga |
|---|---|---|
| **E** | grundläggande kunskaper | fakta, begrepp, enkla beskrivningar |
| **C** | goda kunskaper | förklara samband, ”varför”, ”hur fungerar” |
| **A** | mycket goda kunskaper | resonera, jämföra, dra slutsatser, konsekvenser |

### Textformat i frågor och svar

`**fetstil**`, radbrytningar, kemiska formler i klamrar (`{H2O}` → H₂O) och enkel HTML (`<strong>`, `<sub>`, `<ul>`). Allt annat filtreras bort när det visas.

## Databas

`laroplan/laroplan.db` – se `laroplan/README.md`. Tabeller som appen lägger till (läroplanstabellerna byggs om av `laroplan/bygg.py` utan att röra dessa):

| Tabell | Innehåll |
|---|---|
| `fraga` | fråga, svar, `niva` (E/C/A), tema, samling, källa, granskad, aktiv (visas i flashcards) |
| `fraga_ci` | koppling fråga ↔ `centralt_innehall.nyckel`, plus texten vid kopplingen så att ändringar från Skolverket upptäcks |
| `tema`, `samling` | per ämne |

Frågor kopplas till ämnen via `amne_kod` (t.ex. `GRGRKEM01`) och till läroplanen via den stabila nyckeln `amne_kod:variant:årskurs:ordning`.

## API (lokalt)

`GET /api/amnen` · `GET /api/amne/<kod>` · `GET /api/fragor?amne=<kod>&niva=E,C&tema=<id>&samling=<id>&ci=<nyckel>&q=<sök>` · `GET /api/export?amne=<kod>`
`POST/PUT/DELETE /api/fragor[/<id>]` · `POST /api/fragor/bulk` · `POST/PUT/DELETE /api/teman`, `/api/samlingar` · `POST /api/import`
(skrivningar kräver headern `X-Plugga: 1` och anrop från samma dator)

Den statiska sidan i `docs/` läser samma data som färdiga filer: `data/amnen.json`, `data/amne/<kod>.json`, `data/fragor/<kod>.json`.
