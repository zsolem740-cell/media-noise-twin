"""Elemző és jegyzetelő: csak olvasó. A szavazói exportokból megbeszélő lapot készít egy címcsoportról (horgonykör vagy mérési kör): ki mit szavazott, melyik cím vitatott,
mennyire egyeznek a szavazók, ki mennyire szigorú, és a megbeszélés menete. A lap kizárólag betűket (A, B, ...) és címszövegeket tartalmaz: életkor, nem, név nincs benne.
Nem módosít exportot, nem hív hálózatot, és csak a pilot results/ mappájába ír (git nem követi). A számokat a meglévő elemző (analysis.py) függvényei adják, itt nincs új statisztika.

Parancssor: python -m validation.hu_pilot.briefing EXPORT... [--group anchors|measured] [--out FAJLNEV.html]
A megbeszélés eredménye koordinátori feljegyzés, nem szavazat; a lap semmit nem dönt el."""
import argparse
import html
import json
import statistics
import sys
from pathlib import Path

from . import analysis
from .paths import check_write, load_config, results_dir

SD_CONTESTED = 0.8          # a szavazatok szórása (0/1/2 skálán) ettől vitatott
MAX_QUESTIONS = 6


def _mean_pairs_kappa(rat, voters):
    ks = []
    for i, a in enumerate(voters):
        for b in voters[i + 1:]:
            ps = analysis.pair_stats(rat, a, b)
            if ps["n"] and ps["kappa_weighted"] is not None:
                ks.append(ps["kappa_weighted"])
    return sum(ks) / len(ks) if ks else None


def build(votes, ids, cfg):
    """Visszaad: sorok (a megadott azonosító-sorrendben), szavazók, összesítő számok."""
    rat = analysis.ratings(votes, set(ids))
    titles = {}
    for v in votes:
        titles.setdefault(v["id"], v.get("title", ""))
    voters = sorted({v["voter"] for v in votes if v["id"] in rat})
    rows = []
    for n, i in enumerate((x for x in ids if x in rat), 1):
        r = rat[i]
        vals = list(r.values())
        sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        rows.append({"n": n, "id": i, "title": titles.get(i, ""), "labels": {a: r.get(a) for a in voters}, "mean": sum(vals) / len(vals), "sd": sd,
                     "unanimous": len(set(vals)) == 1 and len(vals) == len(voters), "contested": sd >= SD_CONTESTED, "n_votes": len(vals)})
    full = {i: r for i, r in rat.items() if len(r) == len(voters)}
    strict = {a: (sum(r[a] for r in rat.values() if a in r) / sum(1 for r in rat.values() if a in r)) for a in voters if any(a in r for r in rat.values())}
    stats = {"n_titles": len(rows), "voters": voters, "n_unanimous": sum(r["unanimous"] for r in rows), "n_contested": sum(r["contested"] for r in rows),
             "alpha_ordinal": analysis.krippendorff_alpha([list(r.values()) for r in rat.values()], "ordinal"), "mean_weighted_kappa": _mean_pairs_kappa(rat, voters),
             "strictness": strict, "n_complete_titles": len(full)}
    return rows, voters, stats


def questions(rows, names):
    """A kérdések az adatból jönnek (ki mit szavazott), a cím tartalmáról nem állítanak semmit: a szavazók mondják meg, melyik szavuk döntött."""
    out = []
    for r in sorted((r for r in rows if r["contested"]), key=lambda r: (-r["sd"], r["n"]))[:MAX_QUESTIONS]:
        groups = {}
        for a, v in r["labels"].items():
            if v is not None:
                groups.setdefault(v, []).append(a)
        parts = [f"{', '.join(groups[v])}: {names[str(v)]}" for v in sorted(groups)]
        out.append({"n": r["n"], "text": "; ".join(parts) + ". Melyik szava vagy fordulata döntött? Ugyanazt a szabályt alkalmaznátok rá?"})
    return out


def fmt(x, d=2):
    return "–" if x is None else f"{x:.{d}f}".replace(".", ",")


RULE = [("ny", "Nyugodt", "a cím higgadtan közli a lényeget; nincs benne felkiáltójel, NAGYBETŰ, túlzó vagy érzelmi szó, sem titokzatos ígéret."),
        ("ko", "Közepes", "egy gyenge jel van (kiemelő szó, kérdő vagy csalogató fordulat, idézet), de a cím a lényeget is elmondja; vagy a kettő közt nem tudsz dönteni."),
        ("ha", "Hangos", "több jel együtt vagy egy erős (felkiáltójel, NAGYBETŰ, túlzó jelző, érzelmi nyomás, titokzatos ígéret), akkor is, ha a cikk igaz.")]


def render(rows, voters, stats, qs, names, group_label, date):
    E = html.escape
    cls = {0: "ny", 1: "ko", 2: "ha"}

    def chips(r):
        return "".join(f'<span class="chip {cls[v]}"><b>{E(a)}</b> {E(names[str(v)])}</span>' if v is not None else f'<span class="chip na"><b>{E(a)}</b> –</span>' for a, v in r["labels"].items())
    cards = "".join(f'<li class="card{" hot" if r["contested"] else ""}" data-hot="{int(r["contested"])}"><div class="num">{r["n"]}</div><div class="body"><div class="t">{E(r["title"])}</div>'
                    f'<div class="chips">{chips(r)}</div>{"<span class=flag>vitatott</span>" if r["contested"] else ""}</div></li>' for r in rows)
    strict = " · ".join(f"{E(a)} {fmt(v)}" for a, v in sorted(stats["strictness"].items()))
    rule = "".join(f'<div class="r-{c}"><b>{n}:</b> {E(t)}</div>' for c, n, t in RULE)
    qh = "".join(f"<li><b>{q['n']}. cím.</b> {E(q['text'])}</li>" for q in qs) or "<li>Nincs vitatott cím.</li>"
    return f'''<!doctype html><html lang="hu"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Megbeszélő lap</title>
<style>:root{{--bg:#f5f6f4;--surface:#fff;--fg:#1a2420;--muted:#55645e;--line:#d5dcd8;--accent:#1f7a52;--ny:#e3f1ea;--nyt:#14573a;--ko:#fbefd0;--kot:#6b4a00;--ha:#f9dedb;--hat:#8a1d12}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0e1512;--surface:#16201b;--fg:#e6ede9;--muted:#9bada5;--line:#2a3830;--accent:#3ddc84;--ny:#16342a;--nyt:#8ee6b3;--ko:#3a3115;--kot:#f0cf75;--ha:#3f1f1c;--hat:#ffa89d}}}}
body{{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px}}main{{max-width:720px;margin:0 auto;display:flex;flex-direction:column;gap:18px}}
h1{{font-size:1.5rem;margin:0}}h2{{font-size:.95rem;margin:0 0 8px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}}.box{{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}}.stat{{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px}}.stat b{{display:block;font-size:1.3rem}}.stat span{{color:var(--muted);font-size:.85rem}}
.r-ny{{background:var(--ny);color:var(--nyt)}}.r-ko{{background:var(--ko);color:var(--kot)}}.r-ha{{background:var(--ha);color:var(--hat)}}.box div[class^=r-]{{border-radius:8px;padding:10px 12px;margin-bottom:8px}}
ul,ol{{margin:0;padding-left:1.25rem;display:flex;flex-direction:column;gap:8px}}.list{{list-style:none;padding:0}}.card{{display:flex;gap:12px;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px}}.card.hot{{border:2px solid var(--accent)}}
.num{{font-weight:700;min-width:1.6rem;color:var(--muted)}}.body{{min-width:0;display:flex;flex-direction:column;gap:8px}}.t{{overflow-wrap:anywhere}}.chips{{display:flex;flex-wrap:wrap;gap:6px}}.chip{{font-size:.85rem;padding:2px 8px;border-radius:999px;background:var(--line)}}
.chip.ny{{background:var(--ny);color:var(--nyt)}}.chip.ko{{background:var(--ko);color:var(--kot)}}.chip.ha{{background:var(--ha);color:var(--hat)}}.flag{{font-size:.8rem;font-weight:700;color:var(--accent);text-transform:uppercase}}
.btn{{font:inherit;font-weight:600;border:1px solid var(--line);background:var(--surface);color:var(--fg);border-radius:8px;padding:12px 14px;min-height:48px}}.btn[aria-pressed=true]{{background:var(--accent);color:var(--bg)}}.note{{font-size:.9rem;color:var(--muted)}}</style></head><body><main>
<header><h1>Megbeszélő lap: {E(group_label)}</h1><p class="note">{stats["n_titles"]} cím, szavazók: {E(", ".join(voters))}, {E(date)}. Csak betűk és címszövegek szerepelnek.</p></header>
<section class="stats"><div class="stat"><b>{fmt(stats["alpha_ordinal"])}</b><span>alfa (0 = véletlen, 1 = teljes egyezés)</span></div><div class="stat"><b>{fmt(stats["mean_weighted_kappa"])}</b><span>átlagos páronkénti súlyozott kappa</span></div>
<div class="stat"><b>{stats["n_unanimous"]} / {stats["n_titles"]}</b><span>cím, amin mind egyeznek</span></div><div class="stat"><b>{stats["n_contested"]}</b><span>vitatott cím (szórás ≥ {fmt(SD_CONTESTED, 1)})</span></div></section>
<section class="box"><h2>Szigor szavazónként (0 = csupa Nyugodt, 2 = csupa Hangos)</h2><p>{strict}</p><p class="note">Ha a szigor szavazónként nagyon eltér, a vita fő témája a határ, nem az egyes címek.</p></section>
<section class="box"><h2>Menet (kb. 20 perc)</h2><ol><li>Szabály közös elolvasása (lent), 2 perc: a cím megfogalmazását ítéljük, nem azt, hogy igaz-e, és nem a politikai oldalt.</li><li>Az egyhangú címek gyors átfutása, 5 perc.</li>
<li>A vitatott címek, 10 perc: mindenki egy mondatban elmondja, melyik szavára adta a pontját; a cél a szabály pontosítása, nem a többségi döntés.</li><li>A módosított szabály egy mondatban, lejegyezve. A horgonyokat nem szavazzátok újra.</li></ol></section>
<section class="box"><h2>Javasolt közös szabály (kiindulás, módosítható)</h2>{rule}</section>
<section class="box"><h2>Vitatott címek, kérdésekkel</h2><ul>{qh}</ul></section>
<section><h2>A címek és a szavazatok</h2><p><button class="btn" id="hot" type="button" aria-pressed="false">Csak a vitatottak</button></p><ul class="list" id="list">{cards}</ul></section>
</main><script>(function(){{var b=document.getElementById('hot'),c=document.querySelectorAll('#list .card');b.addEventListener('click',function(){{var on=b.getAttribute('aria-pressed')!=='true';b.setAttribute('aria-pressed',on?'true':'false');c.forEach(function(x){{x.hidden=on&&x.dataset.hot!=='1'}})}});}})();</script></body></html>
'''


def make(paths, cfg, group="anchors", out_name=None, base=None, date=""):
    rdir = results_dir(cfg, base)
    sel = json.loads((rdir / cfg["files"]["selection"]).read_text(encoding="utf-8"))
    ids = sel["anchor_ids"] if group == "anchors" else sel["measured_ids"]
    votes, _rep = analysis.parse_exports(paths, cfg)
    rows, voters, stats = build(votes, ids, cfg)
    if not rows:
        raise ValueError("a megadott exportokban nincs egyetlen vak szavazat sem erre a csoportra")
    qs = questions(rows, cfg["label_names"])
    label = "horgonykör (20 magyar cím)" if group == "anchors" else "mérési kör (magyar címek)"
    page = render(rows, voters, stats, qs, cfg["label_names"], label, date)
    out = check_write(rdir / (out_name or f"megbeszelo_{group}.html"), rdir)
    out.write_text(page, encoding="utf-8")
    return {"file": out.name, "group": group, "stats": stats, "n_questions": len(qs)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("exports", nargs="+")
    ap.add_argument("--group", choices=("anchors", "measured"), default="anchors")
    ap.add_argument("--out")
    ap.add_argument("--date", default="")
    a = ap.parse_args(argv)
    try:
        r = make(a.exports, load_config(), a.group, a.out, date=a.date)
    except (FileNotFoundError, ValueError, KeyError) as e:
        print(f"NEM KÉSZÍTHETŐ: {e}", file=sys.stderr)
        return 2
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
