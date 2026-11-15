# CLAUDE.md — Projektirányelvek és korlátok

## Szolgáltatók és kvótakezelés
- Elsődleges szolgáltató: Gemini.
- Groq használata: kizárólag nem mérési munkán engedélyezett; mérési futáson tilos a szolgáltatóváltás.
- Költség- és szolgáltatókorlát: tilos a fizetős csomagra váltás, és tilos harmadik szolgáltató bevonása.
- Kvótakimerülés: a napi kvóta elérésekor a futás azonnal álljon meg; a már elkészült címek maradjanak meg.
- Újraindítás és próba: a folytatás a kvóta visszaállása után 5 perccel indulhat. Az első kérés mindig próbakérés legyen (naponta legfeljebb 3 próba engedélyezett), a már kész címeket pedig tilos újra elküldeni.

## Naplózás és biztonság
- Kötelező naplómezők: minden kérésnél rögzíteni kell a szolgáltatót, a modellt, a kimenetelt és a felhasznált tokenek számát.
- Titokvédelem: API-kulcsok értéke soha, semmilyen formában nem kerülhet a naplóba vagy a kimenetre.

## Szigorú tiltások
- Tilos módosítani a v1, v2 vagy v3 promptokat.
- Tilos 250 címes futást indítani.
- Tilos bármilyen súlyozást alkalmazni.
- Tilos Pull Requestet nyitni vagy bármit egyesíteni (merge).
- Tilos commitolni a results/ mappa tartalmát.
- Tilos valódi Gemini vagy Groq API-hívást indítani; csak hamis átvitellel tesztelj.

## Kódhelyek
- A magyar pilot kódja: `validation/hu_pilot/` (kiválasztás, csomagolás, modellfuttató, elemzés), tesztjei: `validation/hu_pilot/tests/`.
- A pilot eredményei: `validation/hu_pilot/results/` (git nem követi).
- `src/magyar_pilot/` csak a karbantartót (`maintenance.py`) tartalmazza, pilot-logikát ne tegyél ide.
- Háttérszkriptek: `scripts/code_guard.py`, `scripts/kitchen_dispatch.py`, `scripts/context_snapshot.py`.
- Tesztek: `python -m pytest -m "not live_api"` (a `tests/` és a `validation/hu_pilot/tests/` mappát is futtatja, közös hálózati zárral).

## Munkafolyamatok helye
- A részletes telepítési és pilot-folyamatok a `docs/PILOT_RUNBOOK.md` fájlban vannak, nem itt.
