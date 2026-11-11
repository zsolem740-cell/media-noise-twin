"""Rendszer-egészség: mi az, amit az üzemeltetőnek (a telefon tulajdonosának) tudnia kell?

Az ellenőrzések a futás közben, az adatokból számolhatók, ezért az app is meg tudja mutatni őket
(adat["health"]), a notify.py pedig – ha van NTFY_TOPIC – telefonra is elküldi (12 óránként ismételve).
Ami innen NEM látszik: ha maga a workflow nem indul el. Arra a GitHub saját e-mailes hibajelzése és az app
„Frissítve" mutatója (90 perc fölött borostyán, 3 óra fölött piros) szolgál.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from src.utils.time_helper import now_utc, parse_iso

ROOT = Path(__file__).resolve().parents[2]


def check(out: dict, raw_count: int | None, cfg: dict, now=None, root: Path = ROOT) -> list[dict]:
    h = cfg.get("health") or {}
    now = now or now_utc()
    problems: list[dict] = []

    def add(pid: str, text: str) -> None:
        problems.append({"id": pid, "text": text})

    pubs = [parse_iso(i["published"]) for i in out.get("items", []) if i.get("published")]
    if pubs:
        age_h = (now - max(pubs)).total_seconds() / 3600
        if age_h > h.get("stale_hours", 3):
            add("news_stale", f"nincs friss hír {age_h:.1f} órája – a gyűjtő vagy a hírforrás állhat")
    else:
        add("news_stale", "nincs hír az adatban")

    # régiónkénti frissesség: a kis, helyi források kiesése a globális mutatóból nem látszik
    short = {r["code"]: r.get("short", r["code"]) for r in cfg.get("regions", []) if isinstance(r, dict) and "code" in r}
    by: dict = {}
    for it in out.get("items", []):
        if it.get("published"):
            by.setdefault(it.get("region"), []).append(parse_iso(it["published"]))
    stale = []
    for code, ts in by.items():
        if len(ts) >= h.get("region_min_items", 10):
            age = (now - max(ts)).total_seconds() / 3600
            if age > h.get("region_stale_hours", 30):
                stale.append(f"{short.get(code, code)} ({age:.0f} óra)")
    if stale:
        add("region_stale", "régió nem kapott friss hírt: " + ", ".join(sorted(stale)) + " – lehet, hogy csak csendes a forrás, de a gyűjtő is hibás lehet")

    if raw_count is not None and raw_count < h.get("min_raw", 20):
        add("feed_low", f"a gyűjtő csak {raw_count} hírt hozott (várható: több tucat)")

    rs = (out.get("research") or {}).get("status") or {}
    since = rs.get("failed_since")
    if rs.get("failed") and since and now - parse_iso(since) > timedelta(hours=h.get("price_hours", 24)):
        names = ", ".join(list(rs["failed"])[:4])
        add("price_down", f"az árfolyam-letöltés {len(rs['failed'])} tickeren több mint {h.get('price_hours', 24)} órája hibás ({names})")

    warn = (out.get("config") or {}).get("warning")
    if warn:
        add("config_warn", f"config/user.json hiba: {warn}"[:160])

    fdir = root / "inbox" / "failed"
    failed = sorted(p.name for p in fdir.glob("*.txt")) if fdir.is_dir() else []
    if failed:
        add("inbox_failed", f"elutasított frissítés-csomag: {', '.join(failed[:3])} (lásd inbox/LOG.md)")

    mb = (out.get("summary") or {}).get("bytes", 0) / 1e6
    if mb > h.get("max_mb", 8):
        add("size", f"az adatfájl {mb:.1f} MB – a repó gyorsan nőhet, érdemes az adatot külön ágra tenni")
    return problems
