"""Élő-ellenőr logikája: a már feltöltött pilot-címet nézi meg kívülről, olvasásra (csak GET). Ez a modul hálózatmentes: a lekérőt kapja kívülről; a tényleges lekérés és a parancssori belépő a live csomag pagecheck moduljában van.
Nem telepít, kulcsot nem használ és nem kér, nem ír a tárolóba és a results/ mappába.
Ellenőrzi: a cím főcím (nem előnézeti), nem irányít át másik gépre; az alkalmazás verziója; a feed (`pilot` mező, címek, sorrend, semleges sorok); a `_headers` hatása
(feed: no-store, lap: no-cache és noindex); a robots.txt; és ha megvan a szakasz jegyzéke, hogy a kiszolgált fájlok bájtra azok-e, amiket a telepítés-ellenőr ellenőrzött.
A címek szövegét nem írja ki. Nem a telepítés-ellenőr helyett van: feltöltés ELŐTT az kötelező, ez feltöltés UTÁN mutatja meg, mi fut valójában.
Parancssor: a live csomag pagecheck moduljával indul (lásd docs/DEPLOY_CLOUDFLARE.md): URL [--stage 1|2|4] [--results MAPPA]   (kilépési kód: 0 rendben, 1 hiba, 2 nem olvasható / hibás megadás)
A --stage megadásához kell a `results/` mappa kiválasztása; a jegyzék (deploy/stageN_manifest.json) elhagyható, ha nincs meg."""
import argparse
import hashlib
import json
import re
import sys

from .deploycheck import NEUTRAL_NUMBERS, PILOT, expected_ids
from .paths import load_config, results_dir

HOST_RE = re.compile(r"(?:https://)?([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)/?")
URL_HOST_RE = re.compile(r"https://([^/:@?#]+)")


def normalize_url(url):
    """Csak https, a főcím gépneve: felhasználónév/jelszó, port, útvonal, lekérdezés nélkül. A főcímet (séma + gépnév) adja vissza."""
    m = HOST_RE.fullmatch(url.strip())
    if not m or "." not in m.group(1) or url.strip().lower().startswith("http://"):
        raise ValueError("csak a főcím adható meg https-sel: gépnév, felhasználónév, jelszó, port, útvonal és lekérdezés nélkül")
    return f"https://{m.group(1)}"


def _host(url):
    m = URL_HOST_RE.match(url)
    return m.group(1) if m else None


def _get(fetch, url):
    try:
        return fetch(url)
    except (OSError, TimeoutError, ValueError) as e:                    # az URLError az OSError leszármazottja
        return {"status": None, "headers": {}, "body": b"", "url": url, "error": type(e).__name__}


def run_checks(base, fetch, stage, sel, manifest, cfg):
    out = []

    def chk(name, ok, detail=""):
        out.append({"check": name, "ok": bool(ok), "detail": detail})

    host = _host(base)
    preview = host.endswith(".pages.dev") and host.count(".") > 2
    chk("fo_cim_nem_elonezeti", not preview, f"{host}" + (" (előnézeti cím: másik origin, a szavazatok nem lennének meg a fő URL-en)" if preview else ""))
    idx = _get(fetch, base + "/")
    if idx["status"] != 200:
        chk("lap_elerheto", False, f"HTTP {idx['status']}" + (f" ({idx['error']})" if idx.get("error") else ""))
        return out
    final_host = _host(idx["url"])
    chk("lap_elerheto_es_nem_iranyit_at_masik_gepre", final_host == host, f"HTTP 200; végső gép: {final_host}")
    diag = _get(fetch, base + "/js/modules/diag.js")
    where = idx["body"].decode("utf-8", "replace") + " " + (diag["body"].decode("utf-8", "replace") if diag["status"] == 200 else "")
    want = cfg["deploy"]["app_version"]
    chk("alkalmazas_verzioja", want in where, f"elvárt: {want}" + ("" if want in where else " — a kiszolgált fájlokban nem található (régi telepítés?)"))
    h = idx["headers"]
    chk("lap_cache_control_no_cache", "no-cache" in h.get("cache-control", ""), f"{h.get('cache-control', '(nincs)')}")
    chk("lap_noindex", "noindex" in h.get("x-robots-tag", ""), f"{h.get('x-robots-tag', '(nincs)')}")
    chk("lap_referrer_policy_no_referrer", h.get("referrer-policy", "") == "no-referrer", f"{h.get('referrer-policy', '(nincs)')}")
    rob = _get(fetch, base + "/robots.txt")
    chk("robots_txt_tilt_mindent", rob["status"] == 200 and "Disallow: /" in rob["body"].decode("utf-8", "replace"), f"HTTP {rob['status']}")
    fd = _get(fetch, base + "/atm_history.json")
    chk("feed_elerheto", fd["status"] == 200, f"HTTP {fd['status']}")
    chk("feed_cache_control_no_store", "no-store" in fd["headers"].get("cache-control", ""), f"{fd['headers'].get('cache-control', '(nincs)')}")
    try:
        feed = json.loads(fd["body"].decode("utf-8"))
        items = feed.get("items") or []
    except (ValueError, AttributeError):
        chk("feed_olvashato_json", False, "az atm_history.json nem érvényes JSON (vagy nem objektum)")
        return out
    chk("feed_olvashato_json", True, f"{len(items)} cím")
    ids = [i.get("id") for i in items]
    pilot = feed.get("pilot")
    if stage:
        chk("feed_pilot_mezo", pilot == PILOT[stage], f"{pilot} / elvárt: {PILOT[stage]}")
        exp = expected_ids(stage, sel)
        chk("cimek_pontosan_a_szakaszeiv_sorrendre_is", ids == exp, f"{len(ids)} cím / elvárt: {len(exp)}" + ("" if ids == exp else f"; hiányzik {len(set(exp) - set(ids))}, felesleges {len(set(ids) - set(exp))}"))
    else:
        chk("feed_pilot_mezo_megvan", bool(pilot), f"{pilot} (szakasz nélkül csak megmutatom: {len(items)} cím)")
    bad = [i.get("id") for i in items if not (i.get("source") == "pilot" and i.get("source_domain") == "pilot.invalid" and i.get("link") == "" and i.get("summary") == ""
                                              and i.get("alert") is False and i.get("official") is False and all(i.get(k) == 0 for k in NEUTRAL_NUMBERS) and str(i.get("title") or "").strip())]
    chk("sorok_semlegesek_nincs_forras_link_pontszam", not bad, f"nem semleges sorok: {bad[:3]}")
    if manifest:
        files = manifest.get("files") or {}
        pairs = (("index.html", idx["body"]), ("atm_history.json", fd["body"]))
        diff = [n for n, b in pairs if files.get(n) and hashlib.sha256(b).hexdigest() != files[n]]
        known = [n for n, _ in pairs if files.get(n)]
        chk("kiszolgalt_fajlok_bajtra_a_jegyzek_szerintiek", bool(known) and not diff, f"ellenőrzött: {known}; eltérő: {diff}")
    return out


def main(argv, fetch):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("url")
    ap.add_argument("--stage", choices=sorted(PILOT))
    ap.add_argument("--results")
    a = ap.parse_args(argv)
    cfg = load_config()
    sel = manifest = None
    try:
        base = normalize_url(a.url)
        if a.stage:
            rdir = results_dir(cfg, a.results)
            sel = json.loads((rdir / cfg["files"]["selection"]).read_text(encoding="utf-8"))
            mp = rdir / cfg["deploy"]["dir"] / f"stage{a.stage}_manifest.json"
            manifest = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else None
    except (FileNotFoundError, ValueError, KeyError) as e:
        print(f"NEM OLVASHATÓ / HIBÁS MEGADÁS: {e}", file=sys.stderr)
        return 2
    checks = run_checks(base, fetch, a.stage, sel, manifest, cfg)
    ok = all(c["ok"] for c in checks)
    print(f"=== ÉLŐ-ELLENŐR: {_host(base)}" + (f", {a.stage}. szakasz" if a.stage else "") + " ===")
    for c in checks:
        print(f"[{'OK' if c['ok'] else 'HIBA'}] {c['check']}: {c['detail']}")
    if a.stage and not manifest:
        print("(a szakasz jegyzéke nincs meg: a bájtra egyezést nem ellenőriztem)")
    print("RENDBEN" if ok else "HIBA: ne szavaztass, amíg nincs rendben")
    return 0 if ok else 1
