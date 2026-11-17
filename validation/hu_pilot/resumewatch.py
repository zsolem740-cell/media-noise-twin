"""Folytatás-jelző: csak olvasó segéd a `resume-notify` munkafolyamathoz. Megmondja, mikor érdemes értesíteni a felhasználót, hogy a megállt pilot-modellfuttatás folytatható.
Nem indít futást, nem hív modellszolgáltatót, nem ír a tárolóba; hálózatot sem használ (a GitHub-hívásokat és az értesítést a munkafolyamat végzi, ez a modul csak
a JSON-okat értékeli és az üzenetet állítja össze). Az üzenet csak számokat és a teendő lépéseit tartalmazza: szavazói adat, kulcs, hírcím nincs benne.

Parancsok (mind JSON-t ír a kimenetre):
  python -m validation.hu_pilot.resumewatch pick ARTIFACTS.json            a legfrissebb, le nem járt `pilot-run-*` artifact
  python -m validation.hu_pilot.resumewatch decide REPORT.json --actions-run-id N --run-name X [--notified]
                                                                           REPORT = a `quotawatch --json` kimenete; eldönti, kell-e értesítés, és előállítja az üzenetet
  python -m validation.hu_pilot.resumewatch marker REPORT.json --actions-run-id N   a duplikáció-védő jelölő neve
Kilépési kód: 0 rendben (az eredmény a JSON-ban), 2 a bemenet nem olvasható."""
import argparse
import json
import re
import sys

PREFIX = "pilot-run-"
NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
CONFIRM_WORD = "INDITSD"


def valid_name(s):
    return isinstance(s, str) and bool(NAME_RE.match(s))


def pick_artifact(listing):
    """A legfrissebb le nem járt `pilot-run-<név>` artifact. A név csak biztonságos karakterekből állhat (a shellbe nem kerülhet más)."""
    best = None
    for a in (listing or {}).get("artifacts", []):
        name = a.get("name", "")
        if not name.startswith(PREFIX) or a.get("expired"):
            continue
        run_name = name[len(PREFIX):]
        run = (a.get("workflow_run") or {}).get("id")
        if not valid_name(run_name) or not isinstance(run, int) or run <= 0:
            continue
        key = (a.get("created_at") or "", a.get("id") or 0)
        if best is None or key > best[0]:
            best = (key, {"artifact_name": name, "run_name": run_name, "actions_run_id": run})
    return best[1] if best else None


def marker_name(report, actions_run_id):
    ra = re.sub(r"[^0-9]", "", str(report.get("resume_after_utc") or "")) or "nincs"
    return f"resume-notified-{int(actions_run_id)}-{ra}"


def decide(report, actions_run_id, run_name, notified=False):
    """Értesítés csak akkor kell, ha a futás kvótamegállással állt meg, a folytatási idő letelt, van még próba a kvótanapra, és erről még nem küldtünk értesítést."""
    if not valid_name(run_name):
        return {"notify": False, "reason": "érvénytelen futásnév"}
    if report.get("status") != "stopped_quota":
        return {"notify": False, "reason": f"az állapot nem kvótamegállás ({report.get('status')})"}
    if not report.get("can_resume_now"):
        return {"notify": False, "reason": "a folytatás ideje még nem jött el, vagy elfogyott a napi próba"}
    if notified:
        return {"notify": False, "reason": "erről a megállásról már ment értesítés"}
    return {"notify": True, "reason": "folytatható", "title": f"Pilot: {run_name} folytatható", "message": message(report, actions_run_id, run_name), "marker": marker_name(report, actions_run_id)}


def message(report, actions_run_id, run_name):
    left = report.get("probes_left_today")
    lines = [
        f"A {run_name} futás folytatható: kész {report.get('done')} / {report.get('total')} cím, hátra {report.get('pending')}.",
        f"Szolgáltató: {report.get('provider')}. Próba ma: még {left} maradt.",
        "Teendő (te indítod, én nem): GitHub, Actions, Pilot modellfuttatás, Run workflow:",
        f"provider {report.get('provider')}, mode run, model üres, run_name {run_name}, batch_size 0, resume_run_id {int(actions_run_id)}, confirm {CONFIRM_WORD}.",
        "Az első kérés próba lesz, a kész címek nem mennek ki újra.",
    ]
    if report.get("violations"):
        lines.append(f"FIGYELEM: a Kvótafigyelő {len(report['violations'])} szabálysértést jelez: indítás előtt nézd meg.")
    return "\n".join(lines)


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick")
    p.add_argument("artifacts")
    d = sub.add_parser("decide")
    d.add_argument("report")
    d.add_argument("--actions-run-id", type=int, required=True)
    d.add_argument("--run-name", required=True)
    d.add_argument("--notified", action="store_true")
    m = sub.add_parser("marker")
    m.add_argument("report")
    m.add_argument("--actions-run-id", type=int, required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "pick":
            out = pick_artifact(_load(a.artifacts)) or {}
        elif a.cmd == "decide":
            out = decide(_load(a.report), a.actions_run_id, a.run_name, a.notified)
        else:
            out = {"marker": marker_name(_load(a.report), a.actions_run_id)}
    except (OSError, ValueError, KeyError) as e:
        print(f"NEM OLVASHATÓ: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
