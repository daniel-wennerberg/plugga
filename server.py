#!/usr/bin/env python3
"""Plugga – flashcards för alla ämnen, kopplade till läroplanen (Lgr22).

  python3 server.py                      # startar på http://localhost:8090
  python3 server.py --port 9000 --db laroplan/laroplan.db
  python3 server.py --import fil.json    # läser in frågor (exportformatet) och avslutar
  python3 server.py --bygg-sida          # bygger den statiska sidan i docs/ (GitHub Pages) och avslutar

Flashcards:  http://<dator>:8090/          (fungerar från andra enheter på nätverket)
Admin:       http://localhost:8090/admin   (bara från den här datorn)

Bara Pythons standardbibliotek. Frågorna lagras i samma SQLite-fil som läroplanen.
"""
import argparse, json, re, sqlite3, sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
DB_PATH = HERE / "laroplan" / "laroplan.db"
NIVAER = ("E", "C", "A")

SCHEMA = """
CREATE TABLE IF NOT EXISTS samling (
  id INTEGER PRIMARY KEY, amne_kod TEXT NOT NULL, namn TEXT NOT NULL,
  beskrivning TEXT NOT NULL DEFAULT '', ordning INTEGER NOT NULL DEFAULT 0,
  UNIQUE (amne_kod, namn));
CREATE TABLE IF NOT EXISTS tema (
  id INTEGER PRIMARY KEY, amne_kod TEXT NOT NULL, namn TEXT NOT NULL,
  ordning INTEGER NOT NULL DEFAULT 0, UNIQUE (amne_kod, namn));
CREATE TABLE IF NOT EXISTS fraga (
  id INTEGER PRIMARY KEY,
  amne_kod TEXT NOT NULL,                       -- amne.kod, t.ex. GRGRKEM01
  fraga TEXT NOT NULL,
  svar TEXT NOT NULL DEFAULT '',
  svar_kort TEXT NOT NULL DEFAULT '',           -- förenklat svar (tomt = bara svar finns)
  niva TEXT NOT NULL DEFAULT 'E' CHECK (niva IN ('E','C','A')),
  tema_id INTEGER REFERENCES tema(id) ON DELETE SET NULL,
  samling_id INTEGER REFERENCES samling(id) ON DELETE SET NULL,
  kalla TEXT NOT NULL DEFAULT '',               -- t.ex. 'Stella KEMI 7–9 s. 112'
  granskad INTEGER NOT NULL DEFAULT 0,          -- 1 = nivå och innehåll kontrollerade
  aktiv INTEGER NOT NULL DEFAULT 1,             -- 0 = dold i flashcards
  skapad TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  andrad TEXT NOT NULL DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS fraga_ci (           -- koppling fråga <-> centralt innehåll
  fraga_id INTEGER NOT NULL REFERENCES fraga(id) ON DELETE CASCADE,
  ci_nyckel TEXT NOT NULL,                      -- centralt_innehall.nyckel
  ci_text TEXT NOT NULL DEFAULT '',             -- texten när kopplingen gjordes (upptäcker ändringar)
  PRIMARY KEY (fraga_id, ci_nyckel));
CREATE INDEX IF NOT EXISTS ix_fraga_amne ON fraga (amne_kod, niva);
CREATE INDEX IF NOT EXISTS ix_fraga_ci ON fraga_ci (ci_nyckel);
"""


class ApiError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status, self.msg = status, msg


def connect(path=None):
    db = sqlite3.connect(path or DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db(path):
    if not Path(path).exists():
        sys.exit(f"Hittar inte databasen {path}. Kör först laroplan/bygg.py")
    db = connect(path)
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript(SCHEMA)
    if "svar_kort" not in {r[1] for r in db.execute("PRAGMA table_info(fraga)")}:
        db.execute("ALTER TABLE fraga ADD COLUMN svar_kort TEXT NOT NULL DEFAULT ''")
    db.commit()
    db.close()


rows = lambda cur: [dict(r) for r in cur]


def need_amne(db, kod):
    r = db.execute("SELECT kod FROM amne WHERE kod = ?", (kod,)).fetchone()
    if not r:
        raise ApiError(404, f"Okänt ämne: {kod}")
    return kod


# ---------------------------------------------------------------- läsning
def list_amnen(db):
    return rows(db.execute("""
      SELECT a.kod, a.namn, a.beteckning,
        count(f.id) AS antal,
        sum(f.niva = 'E') AS E, sum(f.niva = 'C') AS C, sum(f.niva = 'A') AS A,
        sum(f.granskad = 0) AS ogranskade
      FROM amne a LEFT JOIN fraga f ON f.amne_kod = a.kod AND f.aktiv = 1
      GROUP BY a.kod ORDER BY a.namn"""))


def get_amne(db, kod):
    need_amne(db, kod)
    a = dict(db.execute("SELECT kod, namn, beteckning, beskrivning, syfte FROM amne WHERE kod = ?", (kod,)).fetchone())
    a["mal"] = [r["text"] for r in db.execute("SELECT text FROM amne_mal WHERE amne_kod = ? ORDER BY ordning", (kod,))]
    a["ci"] = rows(db.execute("""
      SELECT c.nyckel, c.variant, c.variant_namn, c.arskurs, c.omrade, c.ordning, c.text,
        count(f.id) AS antal, sum(f.niva='E') AS E, sum(f.niva='C') AS C, sum(f.niva='A') AS A
      FROM centralt_innehall c
      LEFT JOIN fraga_ci fc ON fc.ci_nyckel = c.nyckel
      LEFT JOIN fraga f ON f.id = fc.fraga_id
      WHERE c.amne_kod = ? GROUP BY c.id ORDER BY c.id""", (kod,)))
    a["betyg"] = rows(db.execute("""SELECT variant, variant_namn, betyg, text FROM betygskriterier
      WHERE amne_kod = ? AND betyg IN ('E','C','A') ORDER BY id""", (kod,)))
    a["teman"] = rows(db.execute("""SELECT t.id, t.namn, t.ordning, count(f.id) AS antal FROM tema t
      LEFT JOIN fraga f ON f.tema_id = t.id WHERE t.amne_kod = ? GROUP BY t.id ORDER BY t.ordning, t.namn""", (kod,)))
    a["samlingar"] = rows(db.execute("""SELECT s.id, s.namn, s.beskrivning, s.ordning, count(f.id) AS antal FROM samling s
      LEFT JOIN fraga f ON f.samling_id = s.id WHERE s.amne_kod = ? GROUP BY s.id ORDER BY s.ordning, s.namn""", (kod,)))
    return a


def list_fragor(db, q):
    kod = need_amne(db, (q.get("amne") or [""])[0])
    where, args = ["f.amne_kod = ?"], [kod]
    one = lambda k: (q.get(k) or [""])[0]
    if one("niva"):
        nv = [n for n in one("niva").split(",") if n in NIVAER]
        where.append(f"f.niva IN ({','.join('?' * len(nv))})" if nv else "0")
        args += nv
    for k, col in (("tema", "f.tema_id"), ("samling", "f.samling_id")):
        v = one(k)
        if v == "ingen":
            where.append(f"{col} IS NULL")
        elif v:
            where.append(f"{col} = ?"); args.append(int(v))
    if one("granskad") in ("0", "1"):
        where.append("f.granskad = ?"); args.append(int(one("granskad")))
    if one("aktiv") in ("0", "1"):
        where.append("f.aktiv = ?"); args.append(int(one("aktiv")))
    if one("ci") == "ingen":
        where.append("NOT EXISTS (SELECT 1 FROM fraga_ci x WHERE x.fraga_id = f.id)")
    elif one("ci"):
        where.append("EXISTS (SELECT 1 FROM fraga_ci x WHERE x.fraga_id = f.id AND x.ci_nyckel = ?)"); args.append(one("ci"))
    if one("q"):
        where.append("(f.fraga LIKE ? OR f.svar LIKE ? OR f.svar_kort LIKE ? OR f.kalla LIKE ?)"); args += [f"%{one('q')}%"] * 4
    out = rows(db.execute(f"""SELECT f.* FROM fraga f
      LEFT JOIN tema t ON t.id = f.tema_id LEFT JOIN samling s ON s.id = f.samling_id
      WHERE {' AND '.join(where)}
      ORDER BY coalesce(s.ordning, 999), coalesce(t.ordning, 999), f.id""", args))
    if out:
        ids = [f["id"] for f in out]
        links = {}
        for r in db.execute(f"""SELECT fc.fraga_id, fc.ci_nyckel, fc.ci_text, c.text AS nu FROM fraga_ci fc
            LEFT JOIN centralt_innehall c ON c.nyckel = fc.ci_nyckel
            WHERE fc.fraga_id IN ({','.join('?' * len(ids))})""", ids):
            links.setdefault(r["fraga_id"], []).append({
                "nyckel": r["ci_nyckel"], "text": r["nu"] or r["ci_text"],
                "status": "saknas" if r["nu"] is None else ("andrad" if r["ci_text"] and r["ci_text"] != r["nu"] else "ok")})
        for f in out:
            f["ci"] = links.get(f["id"], [])
    return out


# ---------------------------------------------------------------- skrivning
def owned(db, table, id_, kod):
    if id_ in (None, "", 0):
        return None
    r = db.execute(f"SELECT amne_kod FROM {table} WHERE id = ?", (int(id_),)).fetchone()
    if not r or r["amne_kod"] != kod:
        raise ApiError(400, f"{table} {id_} hör inte till ämnet")
    return int(id_)


def set_ci(db, fid, kod, nycklar):
    db.execute("DELETE FROM fraga_ci WHERE fraga_id = ?", (fid,))
    for n in dict.fromkeys(nycklar or []):
        c = db.execute("SELECT text FROM centralt_innehall WHERE nyckel = ? AND amne_kod = ?", (n, kod)).fetchone()
        if not c:
            raise ApiError(400, f"Okänd punkt i centralt innehåll: {n}")
        db.execute("INSERT INTO fraga_ci (fraga_id, ci_nyckel, ci_text) VALUES (?,?,?)", (fid, n, c["text"]))


def clean_fraga(db, b, kod):
    fr = (b.get("fraga") or "").strip()
    if not fr:
        raise ApiError(400, "Frågan får inte vara tom")
    niva = b.get("niva", "E")
    if niva not in NIVAER:
        raise ApiError(400, "Nivå måste vara E, C eller A")
    return dict(fraga=fr, svar=(b.get("svar") or "").strip(),
                svar_kort=(b.get("svar_kort") or "").strip(), niva=niva,
                tema_id=owned(db, "tema", b.get("tema_id"), kod),
                samling_id=owned(db, "samling", b.get("samling_id"), kod),
                kalla=(b.get("kalla") or "").strip(), granskad=1 if b.get("granskad") else 0,
                aktiv=0 if b.get("aktiv") is False or b.get("aktiv") == 0 else 1)


def create_fraga(db, b):
    kod = need_amne(db, b.get("amne_kod", ""))
    f = clean_fraga(db, b, kod)
    fid = db.execute(f"INSERT INTO fraga (amne_kod, {', '.join(f)}) VALUES (?, {', '.join('?' * len(f))})",
                     [kod, *f.values()]).lastrowid
    set_ci(db, fid, kod, b.get("ci"))
    return fid


def update_fraga(db, fid, b):
    r = db.execute("SELECT amne_kod FROM fraga WHERE id = ?", (fid,)).fetchone()
    if not r:
        raise ApiError(404, "Frågan finns inte")
    f = clean_fraga(db, b, r["amne_kod"])
    db.execute(f"UPDATE fraga SET {', '.join(k + ' = ?' for k in f)}, andrad = datetime('now','localtime') WHERE id = ?",
               [*f.values(), fid])
    if "ci" in b:
        set_ci(db, fid, r["amne_kod"], b["ci"])


def bulk(db, b):
    ids = [int(i) for i in b.get("ids", [])]
    if not ids:
        return 0
    ph = ",".join("?" * len(ids))
    if b.get("radera"):
        return db.execute(f"DELETE FROM fraga WHERE id IN ({ph})", ids).rowcount
    s = b.get("satt") or {}
    kods = {r[0] for r in db.execute(f"SELECT DISTINCT amne_kod FROM fraga WHERE id IN ({ph})", ids)}
    if len(kods) != 1:
        raise ApiError(400, "Markerade frågor måste vara från samma ämne")
    kod = kods.pop()
    sets, args = [], []
    if "niva" in s:
        if s["niva"] not in NIVAER:
            raise ApiError(400, "Ogiltig nivå")
        sets.append("niva = ?"); args.append(s["niva"])
    for k, t in (("tema_id", "tema"), ("samling_id", "samling")):
        if k in s:
            sets.append(f"{k} = ?"); args.append(owned(db, t, s[k], kod))
    for k in ("granskad", "aktiv"):
        if k in s:
            sets.append(f"{k} = ?"); args.append(1 if s[k] else 0)
    if "ci_lagg_till" in s:
        for fid in ids:
            for n in s["ci_lagg_till"]:
                c = db.execute("SELECT text FROM centralt_innehall WHERE nyckel = ? AND amne_kod = ?", (n, kod)).fetchone()
                if c:
                    db.execute("INSERT OR IGNORE INTO fraga_ci VALUES (?,?,?)", (fid, n, c["text"]))
    if sets:
        db.execute(f"UPDATE fraga SET {', '.join(sets)}, andrad = datetime('now','localtime') WHERE id IN ({ph})", [*args, *ids])
    return len(ids)


def save_group(db, table, b, id_=None):
    namn = (b.get("namn") or "").strip()
    if not namn:
        raise ApiError(400, "Namnet får inte vara tomt")
    extra = {"beskrivning": (b.get("beskrivning") or "").strip()} if table == "samling" else {}
    try:
        if id_ is None:
            kod = need_amne(db, b.get("amne_kod", ""))
            ordning = b.get("ordning")
            if ordning is None:
                ordning = db.execute(f"SELECT coalesce(max(ordning), 0) + 1 FROM {table} WHERE amne_kod = ?", (kod,)).fetchone()[0]
            cols = {"amne_kod": kod, "namn": namn, "ordning": int(ordning), **extra}
            return db.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", list(cols.values())).lastrowid
        cols = {"namn": namn, **extra}
        if b.get("ordning") is not None:
            cols["ordning"] = int(b["ordning"])
        if not db.execute(f"UPDATE {table} SET {', '.join(k + ' = ?' for k in cols)} WHERE id = ?", [*cols.values(), id_]).rowcount:
            raise ApiError(404, "Finns inte")
        return id_
    except sqlite3.IntegrityError:
        raise ApiError(409, f"Det finns redan något som heter ”{namn}”")


# ---------------------------------------------------------------- export / import
def export(db, kod):
    a = get_amne(db, kod)
    fr = list_fragor(db, {"amne": [kod]})
    tn = {t["id"]: t["namn"] for t in a["teman"]}
    sn = {s["id"]: s["namn"] for s in a["samlingar"]}
    return {"format": "plugga-fragor-v1", "amne_kod": kod, "amne": a["namn"],
            "teman": [t["namn"] for t in a["teman"]],
            "samlingar": [{"namn": s["namn"], "beskrivning": s["beskrivning"]} for s in a["samlingar"]],
            "fragor": [{"fraga": f["fraga"], "svar": f["svar"], **({"svar_kort": f["svar_kort"]} if f["svar_kort"] else {}),
                        "niva": f["niva"], "tema": tn.get(f["tema_id"]),
                        "samling": sn.get(f["samling_id"]), "kalla": f["kalla"], "granskad": bool(f["granskad"]),
                        "aktiv": bool(f["aktiv"]), "ci": [c["nyckel"] for c in f["ci"]]} for f in fr]}


def import_data(db, d, ersatt=False):
    kod = need_amne(db, d.get("amne_kod", ""))
    if ersatt:
        db.execute("DELETE FROM fraga WHERE amne_kod = ?", (kod,))
    def group_id(table, namn, beskr=""):
        if not namn:
            return None
        r = db.execute(f"SELECT id FROM {table} WHERE amne_kod = ? AND namn = ?", (kod, namn)).fetchone()
        return r["id"] if r else save_group(db, table, {"amne_kod": kod, "namn": namn, "beskrivning": beskr})
    for s in d.get("samlingar", []):
        group_id("samling", s["namn"], s.get("beskrivning", ""))
    for t in d.get("teman", []):
        group_id("tema", t)
    known = {r[0] for r in db.execute("SELECT nyckel FROM centralt_innehall WHERE amne_kod = ?", (kod,))}
    n = dup = 0
    for f in d.get("fragor", []):
        if not ersatt and db.execute("SELECT 1 FROM fraga WHERE amne_kod = ? AND fraga = ? AND svar = ?",
                                     (kod, f.get("fraga", "").strip(), (f.get("svar") or "").strip())).fetchone():
            dup += 1
            continue
        create_fraga(db, {**f, "amne_kod": kod, "tema_id": group_id("tema", f.get("tema")),
                          "samling_id": group_id("samling", f.get("samling")),
                          "ci": [c for c in f.get("ci", []) if c in known]})
        n += 1
    return {"importerade": n, "dubbletter": dup}


# ---------------------------------------------------------------- http
class Handler(SimpleHTTPRequestHandler):
    server_version = "Plugga/1.0"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB), **kw)

    def log_message(self, fmt, *args):
        if len(args) >= 2 and str(args[1])[:1] in ("2", "3"):
            return  # tyst vid lyckade anrop
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def is_local(self):
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            raise ApiError(400, "Ogiltig JSON")

    def route(self, method):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        if not p.startswith("/api/"):
            if p in ("/admin", "/admin/"):
                if not self.is_local():
                    return self.send_error(HTTPStatus.FORBIDDEN, "Admin går bara att öppna på datorn där servern körs")
                self.path = "/admin.html"
            elif p == "/":
                self.path = "/index.html"
            return super().do_GET() if method == "GET" else self.send_error(405)
        if method != "GET":
            # skrivningar: bara från den här datorn, och bara från appen (egen header => blockerar andra webbplatser)
            if not self.is_local():
                raise ApiError(403, "Ändringar går bara att göra från datorn där servern körs")
            if self.headers.get("X-Plugga") != "1":
                raise ApiError(403, "Saknar X-Plugga-header")
        parts = [x for x in p[5:].split("/") if x]
        db = connect()
        try:
            res = self.dispatch(db, method, parts, q)
            db.commit()
            return self.send_json(res)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def dispatch(self, db, m, parts, q):
        head, rest = parts[0] if parts else "", parts[1:]
        rid = int(rest[0]) if rest and rest[0].isdigit() else None
        if m == "GET":
            if head == "info":
                return {"admin": self.is_local(), "db": str(DB_PATH.name),
                        "laroplan": dict(db.execute("SELECT varde FROM metadata WHERE nyckel='laroplan'").fetchone() or {"varde": ""})["varde"]}
            if head == "amnen":
                return list_amnen(db)
            if head == "amne" and rest:
                return get_amne(db, rest[0])
            if head == "fragor":
                return list_fragor(db, q)
            if head == "export":
                return export(db, (q.get("amne") or [""])[0])
        elif head == "fragor":
            if m == "POST" and rest == ["bulk"]:
                return {"andrade": bulk(db, self.body())}
            if m == "POST" and not rest:
                return {"id": create_fraga(db, self.body())}
            if m == "PUT" and rid:
                update_fraga(db, rid, self.body()); return {"id": rid}
            if m == "DELETE" and rid:
                db.execute("DELETE FROM fraga WHERE id = ?", (rid,)); return {"id": rid}
        elif head in ("teman", "samlingar"):
            table = "tema" if head == "teman" else "samling"
            if m == "POST" and not rest:
                return {"id": save_group(db, table, self.body())}
            if m == "PUT" and rid:
                return {"id": save_group(db, table, self.body(), rid)}
            if m == "DELETE" and rid:
                db.execute(f"DELETE FROM {table} WHERE id = ?", (rid,)); return {"id": rid}
        elif head == "import" and m == "POST":
            b = self.body()
            return import_data(db, b.get("data") or {}, bool(b.get("ersatt")))
        raise ApiError(404, "Okänd adress")

    def handle_api(self, method):
        try:
            self.route(method)
        except ApiError as e:
            self.send_json({"fel": e.msg}, e.status)
        except (ValueError, sqlite3.IntegrityError) as e:
            self.send_json({"fel": str(e)}, 400)

    do_GET = lambda self: self.handle_api("GET")
    do_POST = lambda self: self.handle_api("POST")
    do_PUT = lambda self: self.handle_api("PUT")
    do_DELETE = lambda self: self.handle_api("DELETE")


def bygg_sida(ut):
    """Statisk kopia för GitHub Pages: webbfilerna + frågor och läroplan som JSON (bara ämnen med frågor)."""
    import shutil
    if ut.exists():
        shutil.rmtree(ut)
    (ut / "data" / "amne").mkdir(parents=True)
    (ut / "data" / "fragor").mkdir()
    for f in ("app.css", "common.js", "tidslinje.html"):
        shutil.copy(WEB / f, ut / f)
    if (WEB / "img").exists():
        shutil.copytree(WEB / "img", ut / "img")
    html = (WEB / "index.html").read_text()
    tag = '<script src="common.js"></script>'
    assert tag in html
    (ut / "index.html").write_text(html.replace(tag, '<script>window.PLUGGA_STATISK = true</script>\n' + tag))
    (ut / ".nojekyll").touch()
    w = lambda path, obj: path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    db = connect()
    try:
        amnen = [a for a in list_amnen(db) if a["antal"]]
        w(ut / "data" / "amnen.json", amnen)
        for a in amnen:
            w(ut / "data" / "amne" / f"{a['kod']}.json", get_amne(db, a["kod"]))
            w(ut / "data" / "fragor" / f"{a['kod']}.json",
              list_fragor(db, {"amne": [a["kod"]], "aktiv": ["1"]}))
    finally:
        db.close()
    namn = ", ".join("%s (%d)" % (a["namn"], a["antal"]) for a in amnen)
    print(f"Byggde {ut}: {namn}")


def main():
    global DB_PATH
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = nåbar från nätverket (standard), 127.0.0.1 = bara den här datorn")
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--import", dest="imp", type=Path, help="läs in frågor från en exportfil och avsluta")
    ap.add_argument("--ersatt", action="store_true", help="vid --import: ta först bort ämnets alla frågor")
    ap.add_argument("--bygg-sida", dest="sida", nargs="?", const=HERE / "docs", type=Path,
                    help="bygg statisk sida (bara flashcards, ingen admin) i docs/ och avsluta")
    a = ap.parse_args()
    DB_PATH = a.db.resolve()
    init_db(DB_PATH)
    if a.imp:
        db = connect()
        try:
            r = import_data(db, json.loads(a.imp.read_text()), a.ersatt)
            db.commit()
            print(f"Importerade {r['importerade']} frågor ({r['dubbletter']} dubbletter hoppades över)")
        except ApiError as e:
            sys.exit(e.msg)
        return
    if a.sida:
        bygg_sida(a.sida.resolve())
        return
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"Plugga körs:  flashcards http://localhost:{a.port}/   admin http://localhost:{a.port}/admin   (databas {DB_PATH})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
