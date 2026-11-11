"""ntfy értesítések: hivatalos figyelmeztetés, szokatlanul zajos hír, felszálló téma.

Futtatás:  NTFY_TOPIC=... python -m src.core.notify
A topic titok (GitHub secret); ha nincs megadva, a lépés csendben kihagyódik.
Az elküldött üzenetek azonosítói az atm_history.json "notified" részében vannak (duplikáció ellen).
"""
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import requests

from src.utils.config import load_config
from src.utils.time_helper import now_utc, parse_iso, to_iso_utc

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "sources.json"
HISTORY = ROOT / "data" / "metrics" / "atm_history.json"
NTFY = "https://ntfy.sh"


def build_messages(history: dict, cfg: dict, now=None) -> list[dict]:
    """Új, még el nem küldött üzenetek, fontossági sorrendben (hivatalos riasztás → anomália → téma)."""
    now = now or now_utc()
    n = cfg.get("notify", {})
    state = history.get("notified") or {}
    sent_ids, sent_terms = state.get("ids", {}), state.get("terms", {})
    fresh = now - timedelta(hours=n.get("fresh_hours", 3))
    items = {i["id"]: i for i in history.get("items", [])}
    msgs: list[dict] = []
    health_msgs: list[dict] = []
    hs = state.get("health", {})
    repeat = timedelta(hours=n.get("health_repeat_hours", 12))
    for p in history.get("health", []):
        last = hs.get(p["id"])
        if not last or now - parse_iso(last) >= repeat:
            health_msgs.append({"key": ("health", p["id"]), "title": "Rendszer-figyelmeztetés", "message": p["text"][:300],
                                "click": "", "priority": 4, "tags": ["rotating_light"]})

    for i in items.values():
        if i.get("alert") and i["id"] not in sent_ids and parse_iso(i["published"]) >= now - timedelta(hours=12):
            msgs.append({"key": ("id", i["id"]), "title": f"Hivatalos figyelmeztetés – {i.get('source', '')}",
                         "message": i["title"][:300], "click": i.get("link", ""), "priority": 4, "tags": ["warning"]})

    for a in history.get("insights", {}).get("anomalies", []):
        i = items.get(a["id"])
        if (i and a["id"] not in sent_ids and a["z"] >= n.get("anomaly_z", 3.0) and a["S"] >= n.get("anomaly_min_S", 0.5)
                and parse_iso(i["published"]) >= fresh):
            msgs.append({"key": ("id", a["id"]), "title": f"Szokatlanul zajos: {a.get('source', '')}",
                         "message": f"{a['title'][:240]} (ATM {i['ATM']:g})", "click": i.get("link", ""),
                         "priority": 3, "tags": ["loudspeaker"]})

    for b in history.get("insights", {}).get("bursts", []):
        if b["recent"] >= n.get("burst_min", 8) and b["term"] not in sent_terms:
            msgs.append({"key": ("term", b["term"]), "title": "Felszálló téma",
                         "message": f"„{b['term']}” – {b['recent']} hír az elmúlt 6 órában", "click": "", "priority": 3,
                         "tags": ["chart_with_upwards_trend"]})
    return health_msgs[:2] + msgs[: n.get("max_per_run", 3)]


def mark_sent(history: dict, msgs: list[dict], now=None) -> None:
    now = now or now_utc()
    stamp = to_iso_utc(now)
    state = history.setdefault("notified", {})
    ids, terms, hl = state.setdefault("ids", {}), state.setdefault("terms", {}), state.setdefault("health", {})
    for m in msgs:
        (ids if m["key"][0] == "id" else hl if m["key"][0] == "health" else terms)[m["key"][1]] = stamp
    cutoff = to_iso_utc(now - timedelta(days=3))
    state["ids"] = {k: v for k, v in ids.items() if v >= cutoff}
    state["terms"] = {k: v for k, v in terms.items() if v >= cutoff}
    state["health"] = {k: v for k, v in hl.items() if v >= cutoff}


def send(topic: str, msg: dict, post=requests.post) -> bool:
    body = {"topic": topic, "title": msg["title"], "message": msg["message"], "priority": msg["priority"], "tags": msg["tags"]}
    if msg.get("click"):
        body["click"] = msg["click"]
    try:
        r = post(NTFY, json=body, timeout=10)
        return 200 <= r.status_code < 300
    except Exception as exc:
        print(f"[WARN] ntfy hiba: {exc}", file=sys.stderr)
        return False


def main() -> int:
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic or not HISTORY.exists():
        print("ntfy: nincs beállítva (NTFY_TOPIC), kihagyva.")
        return 0
    try:
        cfg = load_config()[0]
        history = json.loads(HISTORY.read_text(encoding="utf-8"))
        first_run = "notified" not in history or not history["notified"]
        msgs = build_messages(history, cfg)
        ok = [m for m in msgs if send(topic, m)]
        if ok or first_run:
            mark_sent(history, ok)
            HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"ntfy: {len(ok)}/{len(msgs)} üzenet elküldve")
    except Exception as exc:
        print(f"[WARN] ntfy kihagyva: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
