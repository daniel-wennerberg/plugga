#!/usr/bin/env python3
"""Bygger laroplan.db (SQLite) med Lgr22 för grundskolan, årskurs 7–9.

Källa: Skolverkets öppna Syllabus API (https://api.skolverket.se/syllabus/).
Kör igen när Skolverket ändrar något:  python3 bygg.py
Bara standardbiblioteket behövs.

Läroplanstabellerna byggs om på plats. Frågetabellerna (fraga, tema, samling,
fraga_ci) som appen i ../plugga använder rörs aldrig. Frågor kopplas till
centralt innehåll via den stabila kolumnen centralt_innehall.nyckel.
"""
import html, json, re, sqlite3, sys, urllib.request
from datetime import date
from pathlib import Path

API = "https://api.skolverket.se/syllabus/v1"
HERE = Path(__file__).resolve().parent
DB = HERE / "laroplan.db"
YEARS_CC = {"7-9", "4-9"}          # centralt innehåll som gäller åk 7–9
YEARS_KR = {"9"}                   # betygskriterier i slutet av åk 9


def get(path):
    req = urllib.request.Request(API + path, headers={"Accept": "application/json", "User-Agent": "laroplan-bygg/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def clean(s):
    """HTML -> ren text. Tar bort mjuka bindestreck och normaliserar blanksteg."""
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</(p|li|h\d|div)>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("­", "").replace(" ", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\s*\n\s*", "\n", s)
    return s.strip()


def heading(s, tag):
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", s or "", re.S)
    return clean(m.group(1)) if m else ""


def bullets_by_h4(block):
    """Delar ett centralt-innehåll-block i (område, punkt)-par."""
    out, area = [], ""
    for m in re.finditer(r"<h4[^>]*>(.*?)</h4>|<li[^>]*>(.*?)</li>", block, re.S):
        if m.group(1) is not None:
            area = clean(m.group(1))
        else:
            out.append((area, clean(m.group(2))))
    return out


def purpose_goals(purpose):
    """Ämnets långsiktiga mål = punktlistan efter 'förutsättningar att utveckla sin förmåga att'."""
    return [clean(x) for x in re.findall(r"<li[^>]*>(.*?)</li>", purpose or "", re.S)]


def variant_name(block, fallback):
    h = heading(block, "h3")
    m = re.search(r"inom ramen för (.+)$", h, re.I)
    return m.group(1).strip() if m else (fallback or "")


# Läroplansobjekt som byggs om. Barn före föräldrar.
OWN_VIEWS = ["v_oversikt", "v_betygskriterier", "v_centralt_innehall"]
OWN_TABLES = ["sok", "laroplan_underavsnitt", "laroplan_avsnitt", "betygskriterier",
              "centralt_innehall_block", "centralt_innehall", "amne_mal", "amne", "metadata"]

SCHEMA = """
CREATE TABLE metadata (nyckel TEXT PRIMARY KEY, varde TEXT);
CREATE TABLE amne (
  kod TEXT PRIMARY KEY,            -- t.ex. GRGRKEM01
  namn TEXT NOT NULL,              -- t.ex. Kemi
  beteckning TEXT,                 -- t.ex. KE
  typ TEXT,                        -- COURSE_SYLLABUS / OTHER_COURSE_SYLLABUS
  version INTEGER, andrad TEXT, startdatum TEXT, skolfs TEXT, versionsinfo TEXT,
  beskrivning TEXT,                -- inledande text
  syfte TEXT,                      -- hela syftet som ren text
  syfte_html TEXT,
  kalla_url TEXT
);
CREATE TABLE amne_mal (            -- de långsiktiga målen (förmågorna) i syftet
  id INTEGER PRIMARY KEY, amne_kod TEXT REFERENCES amne(kod), ordning INTEGER, text TEXT
);
CREATE TABLE centralt_innehall (   -- en rad per punkt i centralt innehåll åk 7–9
  id INTEGER PRIMARY KEY, amne_kod TEXT REFERENCES amne(kod),
  nyckel TEXT UNIQUE,              -- stabil nyckel: amne_kod:variant:arskurs:ordning (frågor kopplas hit)
  variant TEXT,                    -- t.ex. WITHIN_LANGUAGE_CHOICE, FIN_LANGUAGE_FIRST, tom = ordinarie
  variant_namn TEXT,               -- t.ex. 'språkval', 'finska som förstaspråk'
  arskurs TEXT,                    -- '7-9' (eller '4-9' för skolans val)
  omrade TEXT,                     -- rubriken punkten står under
  ordning INTEGER, text TEXT
);
CREATE TABLE centralt_innehall_block (
  id INTEGER PRIMARY KEY, amne_kod TEXT REFERENCES amne(kod), variant TEXT, variant_namn TEXT,
  arskurs TEXT, rubrik TEXT, text TEXT, html TEXT
);
CREATE TABLE betygskriterier (     -- slutet av åk 9, betyg E–A
  id INTEGER PRIMARY KEY, amne_kod TEXT REFERENCES amne(kod),
  variant TEXT, variant_namn TEXT, arskurs TEXT, betyg TEXT, text TEXT, html TEXT
);
CREATE TABLE laroplan_avsnitt (    -- Lgr22 del 1–3: värdegrund, mål och riktlinjer m.m.
  id INTEGER PRIMARY KEY, ordning INTEGER, typ TEXT, rubrik TEXT, text TEXT, html TEXT
);
CREATE TABLE laroplan_underavsnitt (
  id INTEGER PRIMARY KEY, avsnitt_id INTEGER REFERENCES laroplan_avsnitt(id),
  ordning INTEGER, rubrik TEXT, text TEXT
);
CREATE VIRTUAL TABLE sok USING fts5(amne, del, rubrik, text, tokenize='unicode61 remove_diacritics 0');

CREATE VIEW v_centralt_innehall AS
  SELECT a.namn AS amne, c.variant_namn, c.arskurs, c.omrade, c.ordning, c.text
  FROM centralt_innehall c JOIN amne a ON a.kod = c.amne_kod
  ORDER BY a.namn, c.variant, c.id;
CREATE VIEW v_betygskriterier AS
  SELECT a.namn AS amne, b.variant_namn, b.betyg, b.text
  FROM betygskriterier b JOIN amne a ON a.kod = b.amne_kod
  ORDER BY a.namn, b.variant, instr('EDCBA', b.betyg);
CREATE VIEW v_oversikt AS
  SELECT a.namn AS amne, a.kod, a.beteckning,
    (SELECT count(*) FROM amne_mal m WHERE m.amne_kod = a.kod) AS mal,
    (SELECT count(*) FROM centralt_innehall c WHERE c.amne_kod = a.kod) AS punkter_centralt_innehall,
    (SELECT count(*) FROM betygskriterier b WHERE b.amne_kod = a.kod) AS betygskriterier
  FROM amne a ORDER BY a.namn;
"""


def main():
    db = sqlite3.connect(DB)
    db.execute("PRAGMA foreign_keys = OFF")
    db.execute("BEGIN")
    for v in OWN_VIEWS:
        db.execute(f"DROP VIEW IF EXISTS {v}")
    for t in OWN_TABLES:
        db.execute(f"DROP TABLE IF EXISTS {t}")
    for stmt in SCHEMA.split(";"):
        if stmt.strip():
            db.execute(stmt)
    fts = lambda *r: db.execute("INSERT INTO sok VALUES (?,?,?,?)", r)

    subjects = get("/subjects?schooltype=GR&timespan=LATEST")["subjects"]
    for s in subjects:
        x = get(f"/subjects/{s['code']}?timespan=LATEST")["subject"]
        name = x["name"]
        print(f"  {name}", file=sys.stderr)
        db.execute("INSERT INTO amne VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            x["code"], name, x.get("designation"), x.get("typeOfSyllabus"), x.get("version"),
            x.get("modifiedDate"), x.get("startDate"),
            f"SKOLFS {x.get('skolfsGrund')}" + (f", ändrad {x['skolfsAndring']}" if x.get("skolfsAndring") else ""),
            x.get("versionInfo"), clean(x.get("description")), clean(x.get("purpose")), x.get("purpose"),
            f"{API}/subjects/{x['code']}"))
        fts(name, "syfte", "Syfte", clean(x.get("purpose")))
        for i, g in enumerate(purpose_goals(x.get("purpose")), 1):
            db.execute("INSERT INTO amne_mal (amne_kod, ordning, text) VALUES (?,?,?)", (x["code"], i, g))

        for cc in x.get("centralContents", []):
            if cc["year"] not in YEARS_CC:
                continue
            var = cc.get("typeOfCentralContent") or ""
            vn = variant_name(cc["text"], "")
            db.execute("INSERT INTO centralt_innehall_block (amne_kod, variant, variant_namn, arskurs, rubrik, text, html) VALUES (?,?,?,?,?,?,?)",
                       (x["code"], var, vn, cc["year"], heading(cc["text"], "h3"), clean(cc["text"]), cc["text"]))
            for i, (area, txt) in enumerate(bullets_by_h4(cc["text"]), 1):
                db.execute("INSERT INTO centralt_innehall (amne_kod, nyckel, variant, variant_namn, arskurs, omrade, ordning, text) VALUES (?,?,?,?,?,?,?,?)",
                           (x["code"], f"{x['code']}:{var}:{cc['year']}:{i}", var, vn, cc["year"], area, i, txt))
                fts(name, "centralt innehåll" + (f" ({vn})" if vn else ""), area, txt)

        for kr in x.get("knowledgeRequirements", []):
            if kr.get("year") not in YEARS_KR:
                continue
            var = kr.get("typeOfRequirement") or ""
            vn = variant_name(kr["text"], "") if kr["text"].lstrip().startswith("<h3>Inom") else ""
            body = re.sub(r"^\s*<h3>Inom ramen[^<]*</h3>", "", kr["text"])
            body = re.sub(r"^\s*<h3>[^<]*</h3>", "", body)
            db.execute("INSERT INTO betygskriterier (amne_kod, variant, variant_namn, arskurs, betyg, text, html) VALUES (?,?,?,?,?,?,?)",
                       (x["code"], var, vn, kr["year"], kr.get("gradeStep"), clean(body), kr["text"]))
            fts(name, f"betyg {kr.get('gradeStep')} åk 9", vn, clean(body))

    # variant_namn för betygskriterier: fyll från centralt innehåll med samma variant
    db.execute("""UPDATE betygskriterier SET variant_namn = (
        SELECT c.variant_namn FROM centralt_innehall_block c
        WHERE c.amne_kod = betygskriterier.amne_kod AND c.variant = betygskriterier.variant LIMIT 1)
        WHERE variant <> '' AND (variant_namn IS NULL OR variant_namn = '')""")

    cur = get("/curriculums/LGR22?timespan=LATEST")
    cur = cur.get("curriculum", cur)
    for sec in cur["sections"]:
        rub = heading(sec["heading"], "h2")
        aid = db.execute("INSERT INTO laroplan_avsnitt (ordning, typ, rubrik, text, html) VALUES (?,?,?,?,?)",
                         (sec.get("sortOrder"), sec.get("type"), rub, clean(sec["content"]), sec["content"])).lastrowid
        parts = re.split(r"(<h[23][^>]*>.*?</h[23]>)", sec["content"], flags=re.S)
        h, i = rub, 0
        for p in parts:
            if re.match(r"<h[23]", p):
                h = clean(p)
            elif clean(p):
                i += 1
                db.execute("INSERT INTO laroplan_underavsnitt (avsnitt_id, ordning, rubrik, text) VALUES (?,?,?,?)", (aid, i, h, clean(p)))
                fts("Läroplan (Lgr22)", rub, h, clean(p))

    meta = {"kalla": "Skolverket, Syllabus API", "api": API, "laroplan": cur["name"],
            "laroplan_kod": cur["code"], "laroplan_version": str(cur.get("version")),
            "laroplan_andrad": cur.get("modifiedDate"), "skolform": "Grundskolan (GR)",
            "arskurser": "7–9 (centralt innehåll 7–9 samt 4–9 för skolans val; betygskriterier slutet av åk 9)",
            "hamtad": date.today().isoformat()}
    db.executemany("INSERT INTO metadata VALUES (?,?)", meta.items())
    db.commit()
    db.execute("VACUUM")
    db.close()
    print(f"Klar: {DB}", file=sys.stderr)


if __name__ == "__main__":
    main()
