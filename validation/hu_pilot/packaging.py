"""A pilot telepíthető csomagja (Cloudflare Pages, közvetlen feltöltés): a v47.10 alkalmazás `public/` mappája VÁLTOZATLANUL + a szakasz semleges pilot-feedje (`atm_history.json`).
Az alkalmazás kódjához nem nyúl; csak másol, ellenőriz és ZIP-be csomagol. Hálózati kód nincs.
Ellenőrzések: az alkalmazás verziója, csak engedélyezett fájltípusok, a feed pontosan a szakasz címei (nincs más szakasz címe, nincs pontszám), nincs valódi hírmentés a csomagban."""
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

from .paths import check_write

HEADERS = """/atm_history.json
  Cache-Control: no-store
/index.html
  Cache-Control: no-cache
/sw.js
  Cache-Control: no-cache
/*
  X-Robots-Tag: noindex, nofollow
  Referrer-Policy: no-referrer
"""
ROBOTS = "User-agent: *\nDisallow: /\n"
FEED_NAME = "atm_history.json"
ZIP_TIME = (2000, 1, 1, 0, 0, 0)


class PackageError(Exception):
    pass


def app_version(app_dir):
    m = re.search(r"APP_VERSION\s*=\s*'([^']+)'", (Path(app_dir) / "js/modules/diag.js").read_text(encoding="utf-8"))
    return m.group(1) if m else None


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _texts(items):
    out = []
    for t in items:
        out += [t, json.dumps(t, ensure_ascii=False)[1:-1], json.dumps(t)[1:-1]]
    return out


def build_site(app_dir, feed, out_dir, rdir, cfg):
    d = cfg["deploy"]
    app_dir, out_dir = Path(app_dir), Path(out_dir)
    check_write(out_dir / "x", rdir)
    if not (app_dir / "index.html").exists() or not (app_dir / "js/app.js").exists():
        raise PackageError("az app-mappa nem a public/ mappa (hiányzik az index.html vagy a js/app.js)")
    v = app_version(app_dir)
    if v != d["app_version"]:
        raise PackageError(f"az alkalmazás verziója {v!r}, kellene: {d['app_version']!r}")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    for f in sorted(app_dir.rglob("*")):
        rel = f.relative_to(app_dir)
        if f.is_dir() or f.name == FEED_NAME or any(part.startswith(".") for part in rel.parts):
            continue                                                       # a mappában esetleg lévő feed vagy rejtett fájl nem kerül be
        (out_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, out_dir / rel)
    (out_dir / FEED_NAME).write_text(json.dumps(feed, ensure_ascii=False), encoding="utf-8")
    (out_dir / "_headers").write_text(HEADERS, encoding="utf-8")
    (out_dir / "robots.txt").write_text(ROBOTS, encoding="utf-8")
    return out_dir


def verify_site(out_dir, expected_titles, forbidden_titles, cfg):
    """Üres lista = a csomag megfelel. expected_titles: pontosan ezek (sorrendben) szerepelhetnek a feedben; forbidden_titles: egyik fájlban sem lehetnek."""
    d, errs, out_dir = cfg["deploy"], [], Path(out_dir)
    files = sorted(p for p in out_dir.rglob("*") if p.is_file())
    for p in files:
        rel = p.relative_to(out_dir).as_posix()
        if rel not in d["allowed_extra_files"] and p.suffix.lower() not in d["allowed_ext"]:
            errs.append(f"nem engedélyezett fájl: {rel}")
        if any(part.startswith(".") for part in p.relative_to(out_dir).parts):
            errs.append(f"rejtett fájl: {rel}")
    feed_p = out_dir / FEED_NAME
    if not feed_p.exists():
        return errs + ["hiányzik az atm_history.json"]
    feed = json.loads(feed_p.read_text(encoding="utf-8"))
    titles = [i.get("title") for i in feed.get("items", [])]
    if titles != list(expected_titles):
        errs.append("a feed címei nem pontosan a szakasz címei (vagy a sorrendjük más)")
    for i in feed.get("items", []):
        if any(i.get(k) != 0 for k in ("S", "S0", "V", "V0", "G", "ATM", "lat", "lng")) or i.get("source") != "pilot" or i.get("link") or i.get("summary"):
            errs.append(f"nem semleges sor: {i.get('id')}")
            break
    if feed.get("profiles"):
        errs.append("a feed profilokat tartalmaz")
    others = [p for p in files if p.name.endswith(".json") and p.name not in (FEED_NAME, "manifest.json")]
    if others:
        errs.append("váratlan JSON-fájl: " + ", ".join(p.name for p in others))
    needles = _texts([t for t in forbidden_titles if t])
    for p in files:
        if p.suffix.lower() in (".png", ".ico"):
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        if any(n in txt for n in needles):
            errs.append(f"más szakasz címe szerepel a(z) {p.relative_to(out_dir).as_posix()} fájlban")
    h = (out_dir / "_headers").read_text(encoding="utf-8") if (out_dir / "_headers").exists() else ""
    if "/atm_history.json" not in h or "no-store" not in h:
        errs.append("a _headers nem állítja a feedet no-store-ra")
    return errs


def make_zip(site_dir, zip_path, rdir):
    """Determinisztikus ZIP (rendezett sorrend, rögzített időbélyeg), az index.html a gyökérben."""
    zp = check_write(zip_path, rdir)
    zp.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(Path(site_dir).rglob("*")):
            if p.is_file():
                zi = zipfile.ZipInfo(p.relative_to(site_dir).as_posix(), ZIP_TIME)
                zi.compress_type, zi.external_attr = zipfile.ZIP_DEFLATED, 0o644 << 16
                z.writestr(zi, p.read_bytes())
    return zp


def manifest(site_dir, zip_path, stage, cfg, app_commit=None):
    site_dir = Path(site_dir)
    return {"stage": stage, "app_version": cfg["deploy"]["app_version"], "app_commit": app_commit, "zip": Path(zip_path).name, "zip_sha256": sha256_file(zip_path),
            "files": {p.relative_to(site_dir).as_posix(): sha256_file(p) for p in sorted(site_dir.rglob("*")) if p.is_file()}}
