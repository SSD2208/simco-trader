#!/usr/bin/env python3
"""
Collecteur de prix Sim Companies (via l'API publique SimcoTools).

A chaque passage (toutes les 30 min via GitHub Actions) :
  1. recupere l'etat precedent (publie sur GitHub Pages) ;
  2. releve le prix le plus bas actuel de chaque objet / qualite ;
  3. une fois par jour, recharge l'historique journalier (90 jours) de chaque objet ;
  4. reconstruit le site : data/summary.json (vue d'ensemble), data/k/<id>_<q>.json
     (detail par objet) et data/state.json (etat pour le prochain passage).

Uniquement la bibliotheque standard de Python.
"""
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:  # pragma: no cover
    PARIS = timezone(timedelta(hours=1))

REALM = int(os.environ.get("REALM", "1"))
API_BASE = os.environ.get("API_BASE", "https://api.simcotools.com/v1/realms").rstrip("/")
API = f"{API_BASE}/{REALM}"
PAGES_URL = os.environ.get("PAGES_URL", "").rstrip("/")
STATE_FILE = os.environ.get("STATE_FILE", "")  # pour les tests en local
OUT_DIR = os.environ.get("OUT_DIR", "_site")
SITE_SRC = os.environ.get("SITE_SRC", os.path.join(os.path.dirname(__file__), "..", "site"))
SLEEP = float(os.environ.get("SLEEP", "0.8"))       # pause entre deux appels a l'API
CANDLE_MAX_AGE_H = float(os.environ.get("CANDLE_MAX_AGE_H", "20"))
INTRADAY_DAYS = 14
CANDLE_DAYS = 90
SUMMARY_DAYS = 60
UA = "simco-trader/1.0 (tableau de bord perso, GitHub Actions)"
GAME_API = os.environ.get("GAME_API", "https://www.simcompanies.com/api/v4")
LANG = os.environ.get("LANG_NAMES", "fr")

_last_call = [0.0]


def log(*a):
    print(*a, flush=True)


def http_json(url, tries=3, polite=True):
    """GET JSON avec reessais. Leve HTTPError tel quel pour un 404."""
    last = None
    for attempt in range(tries):
        if polite:
            wait = SLEEP - (time.time() - _last_call[0])
            if wait > 0:
                time.sleep(wait)
            _last_call[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA,
                                                       "Accept-Encoding": "identity"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = e
            if e.code == 429:
                time.sleep(20 * (attempt + 1))
            else:
                time.sleep(3 * (attempt + 1))
        except Exception as e:  # reseau, JSON...
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Echec apres {tries} essais : {url} ({last})")


def sig(x, n=5):
    """Arrondi a n chiffres significatifs (pour alleger les fichiers)."""
    if x is None:
        return None
    x = float(x)
    if x == 0:
        return 0
    return float(f"{x:.{n}g}")


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ---------------------------------------------------------------- etat precedent
def load_state():
    if STATE_FILE:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        return {}
    if not PAGES_URL:
        log("PAGES_URL absent : on repart de zero.")
        return {}
    url = f"{PAGES_URL}/data/state.json?t={int(time.time())}"
    try:
        st = http_json(url, polite=False)
        log(f"Etat precedent charge ({len(st.get('keys', {}))} objets).")
        return st
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log("Pas encore d'etat publie (premier passage) : on repart de zero.")
            return {}
        raise
    # Toute autre erreur fait echouer le passage : mieux vaut sauter un releve
    # que d'ecraser l'historique accumule.


# ---------------------------------------------------------------- collecte
def fetch_resources():
    data = http_json(f"{API}/resources?disable_pagination=True")
    res = data.get("resources", data if isinstance(data, list) else [])
    out = {}
    for r in res:
        out[str(r["id"])] = {"n": r.get("name", f"#{r['id']}"), "r": bool(r.get("isResearch")), "t": float(r.get("transportation") or 0)}
    # Si la pagination n'a pas ete desactivee, on parcourt les pages
    meta = data.get("metadata") if isinstance(data, dict) else None
    if meta and meta.get("lastPage", 1) > 1 and len(out) < meta.get("totalRecords", 0):
        for page in range(2, meta["lastPage"] + 1):
            d = http_json(f"{API}/resources?page={page}")
            for r in d.get("resources", []):
                out[str(r["id"])] = {"n": r.get("name", f"#{r['id']}"), "r": bool(r.get("isResearch")), "t": float(r.get("transportation") or 0)}
    return out


def _fr_entries(data):
    """Extrait (id, nom) d'une reponse de l'encyclopedie du jeu, quel que soit son format."""
    if isinstance(data, dict):
        for key in ("resources", "results", "data"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data] if "name" in data else list(data.values())
    out = {}
    for e in data if isinstance(data, list) else []:
        if not isinstance(e, dict):
            continue
        rid = e.get("db_letter", e.get("id", e.get("kind")))
        name = e.get("name")
        if rid is not None and isinstance(name, str) and name.strip():
            out[str(rid)] = name.strip()
    return out


def add_french_names(resources, state):
    """Ajoute le nom francais ("fr") de chaque ressource, tire de l'encyclopedie du jeu.
    Une seule tentative par jour ; en cas d'echec on garde les noms anglais."""
    missing = [k for k, r in resources.items() if not r.get("fr")]
    if not missing:
        return
    tried = state.get("frTriedAt")
    if tried and (datetime.now(timezone.utc) - parse_dt(tried)).total_seconds() < 20 * 3600:
        return
    state["frTriedAt"] = datetime.now(timezone.utc).isoformat()
    names = {}
    try:
        names = _fr_entries(http_json(f"{GAME_API}/{LANG}/{REALM}/encyclopedia/resources/"))
        log(f"Noms en francais (liste) : {len(names)}")
    except Exception as e:
        log(f"! Liste des noms en francais indisponible : {e}")
    if len(names) < len(missing) * 0.5:
        # repli : une fiche par ressource (une seule fois, les noms sont ensuite gardes)
        errors = 0
        for k in missing:
            if k in names:
                continue
            try:
                names.update(_fr_entries(http_json(f"{GAME_API}/{LANG}/{REALM}/encyclopedia/resources/0/{k}/", tries=1)))
                errors = 0
            except Exception as e:
                errors += 1
                log(f"! Nom francais de #{k} indisponible : {e}")
                if errors >= 3:  # le site du jeu ne repond pas : on abandonne pour aujourd'hui
                    break
        log(f"Noms en francais (fiches) : {len(names)}")
    for k, n in names.items():
        if k in resources:
            resources[k]["fr"] = n


def fetch_prices():
    data = http_json(f"{API}/market/prices")
    rows = data.get("prices", data if isinstance(data, list) else [])
    out = {}
    for p in rows:
        if p.get("price") is None:
            continue
        out[f"{p['resourceId']}_{p['quality']}"] = (float(p["price"]), p.get("datetime"))
    return out


def fetch_candles(rid, q):
    data = http_json(f"{API}/market/resources/{rid}/{q}/candlesticks")
    rows = data.get("candlesticks") or data.get("results") or (data if isinstance(data, list) else [])
    out = []
    for c in rows:
        day = (c.get("date") or c.get("datetime") or "")[:10]
        if not day:
            continue
        out.append([day, sig(c.get("low")), sig(c.get("high")), sig(c.get("close")),
                    int(c.get("volume") or 0), sig(c.get("vwap") if c.get("vwap") is not None else c.get("close"))])
    out.sort(key=lambda r: r[0])
    return out[-CANDLE_DAYS:]


# ---------------------------------------------------------------- calculs
def hour_profile(intraday):
    """Ecart moyen du prix par heure (heure de Paris) par rapport a la moyenne du jour.
    Renvoie (liste de 24 valeurs ou None, nombre de jours utilises)."""
    by_day = {}
    for t, p in intraday:
        dt = datetime.fromtimestamp(t * 60, tz=timezone.utc).astimezone(PARIS)
        by_day.setdefault(dt.date().isoformat(), []).append((dt.hour, p))
    sums = [0.0] * 24
    counts = [0] * 24
    days = 0
    for pts in by_day.values():
        if len(pts) < 12:  # journee trop incomplete
            continue
        mean = sum(p for _, p in pts) / len(pts)
        if mean <= 0:
            continue
        days += 1
        for h, p in pts:
            sums[h] += p / mean - 1
            counts[h] += 1
    prof = [round(sums[h] / counts[h], 4) if counts[h] else None for h in range(24)]
    return prof, days


def build_summary_item(key, price, pdt, candles, intraday):
    rid, q = key.split("_")
    c = candles[-SUMMARY_DAYS:]
    item = {"k": key, "id": int(rid), "q": int(q), "p": sig(price), "pt": pdt}
    if c:
        d0 = datetime.fromisoformat(c[0][0]).date()
        item["d0"] = c[0][0]
        item["d"] = [(datetime.fromisoformat(r[0]).date() - d0).days for r in c]
        item["l"] = [r[1] for r in c]
        item["h"] = [r[2] for r in c]
        item["vol"] = [r[4] for r in c]
        item["v"] = [r[5] for r in c]
    prof, days = hour_profile(intraday)
    if days >= 3:
        item["hp"] = prof
        item["hpd"] = days
    # mini-historique intraday sur 48 h (1 point par heure) pour la courbe
    if intraday:
        cutoff = intraday[-1][0] - 48 * 60
        last = {}
        for t, p in intraday:
            if t >= cutoff:
                last[t // 60] = p
        item["i"] = [[h, p] for h, p in sorted(last.items())]
    return item


# ---------------------------------------------------------------- principal
def main():
    t0 = time.time()
    now = parse_dt(os.environ["NOW_ISO"]) if os.environ.get("NOW_ISO") else datetime.now(timezone.utc)
    now_min = int(now.timestamp() // 60)
    state = load_state()
    keys = state.get("keys", {})
    resources = state.get("resources", {})

    prices = fetch_prices()
    log(f"{len(prices)} prix releves.")
    if not prices:
        raise SystemExit("Aucun prix recu : passage annule pour ne pas abimer l'historique.")

    # --- releve intraday
    for key, (price, _) in prices.items():
        k = keys.setdefault(key, {"c": [], "i": []})
        k["i"].append([now_min, sig(price)])
        cutoff = now_min - INTRADAY_DAYS * 24 * 60
        k["i"] = [pt for pt in k["i"] if pt[0] >= cutoff]

    # --- historique journalier (1 fois par jour + nouveaux objets)
    cand_at = state.get("candlesAt")
    stale = (not cand_at) or (now - parse_dt(cand_at)).total_seconds() > CANDLE_MAX_AGE_H * 3600
    todo = [key for key in prices if stale or not keys[key]["c"]]
    if stale or not resources or any("t" not in r for r in resources.values()):
        try:
            fresh = fetch_resources()
            for k, r in fresh.items():  # on garde les noms francais deja connus
                if resources.get(k, {}).get("fr"):
                    r["fr"] = resources[k]["fr"]
            resources = fresh or resources
            log(f"{len(resources)} ressources.")
        except Exception as e:
            log(f"! Liste des ressources indisponible : {e}")
    try:
        add_french_names(resources, state)
    except Exception as e:
        log(f"! Noms en francais : {e}")
    ok = fail = 0
    for n, key in enumerate(todo):
        if time.time() - t0 > 18 * 60:  # garde-fou : on finira au prochain passage
            log("Temps limite atteint, la suite au prochain passage.")
            break
        rid, q = key.split("_")
        try:
            keys[key]["c"] = fetch_candles(rid, q)
            ok += 1
        except urllib.error.HTTPError as e:
            if e.code == 404:
                keys[key]["c"] = keys[key].get("c", [])
            fail += 1
        except Exception as e:
            fail += 1
            log(f"! historique {key} : {e}")
        if (n + 1) % 100 == 0:
            log(f"  historiques : {n + 1}/{len(todo)}")
    if todo:
        log(f"Historiques recharges : {ok} ok, {fail} echecs.")
    if stale and ok > len(todo) * 0.5:
        state["candlesAt"] = now.isoformat()

    # --- objets plus listes depuis longtemps : on les oublie
    old = now_min - INTRADAY_DAYS * 24 * 60
    for key in list(keys):
        if key not in prices and (not keys[key]["i"] or keys[key]["i"][-1][0] < old):
            del keys[key]

    # --- sorties
    data_dir = os.path.join(OUT_DIR, "data")
    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(os.path.join(data_dir, "k"))
    for name in os.listdir(SITE_SRC):
        src = os.path.join(SITE_SRC, name)
        if os.path.isfile(src):
            shutil.copy(src, os.path.join(OUT_DIR, name))

    items = []
    for key, k in keys.items():
        if key not in prices:
            continue
        price, pdt = prices[key]
        items.append(build_summary_item(key, price, pdt, k["c"], k["i"]))
        with open(os.path.join(data_dir, "k", f"{key}.json"), "w", encoding="utf-8") as f:
            json.dump({"c": k["c"], "i": k["i"]}, f, separators=(",", ":"))

    summary = {
        "generatedAt": now.isoformat(),
        "realm": REALM,
        "candlesAt": state.get("candlesAt"),
        "resources": resources,
        "items": items,
    }
    with open(os.path.join(data_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, separators=(",", ":"), ensure_ascii=False)

    state = {"version": 1, "candlesAt": state.get("candlesAt"), "frTriedAt": state.get("frTriedAt"),
             "resources": resources, "keys": keys,
             "savedAt": now.isoformat()}
    with open(os.path.join(data_dir, "state.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, separators=(",", ":"), ensure_ascii=False)
    with open(os.path.join(OUT_DIR, ".nojekyll"), "w") as f:
        f.write("")
    log(f"Termine en {time.time() - t0:.0f} s : {len(items)} objets publies.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        log(f"ERREUR : {e}")
        sys.exit(1)
