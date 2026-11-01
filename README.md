# Média-Zaj Twin (v38)

Vas megye / Alpokalja információs zaj-mérője. **ATM = G · S · (1 − V)**

| Jel | Jelentés | Honnan |
|---|---|---|
| G | gerjesztés (érzelmi töltet) | indulatszavak, felkiáltójel, NAGYBETŰ, kérdés-horog |
| S | szenzáció (kattintásvadász jelleg) | csalogató szavak, listás cím, három pont, felsőfok |
| V | valóságtartalom (ellenőrizhetőség) | hivatalos forrás, bizalom, számok/idézet/hivatkozás, több független forrás, fizikai mérés |

A mutató **kísérleti és tájékoztató**, nem igazságmérő. A súlyok és a szólisták a `config/sources.json` és a `scripts/mnt_server.py` fájlban állíthatók.

## Működés
* 15 percenként a GitHub Actions (`.github/workflows/media-noise.yml`) összegyűjti a híreket (Google News, BBC, NY Post, HungaroMet szöveges figyelmeztetések), pontozza, eseményekbe csoportosítja (koszinusz-hasonlóság), forrásprofilt vezet (Welford), felszálló kifejezéseket keres.
* Csak akkor ír és commitol, ha az adat érdemben változott.
* A kliens (`index.html`) a `data/articles.json` fájlt olvassa; a 3D glóbusz Three.js InstancedMesh, a szűrő a telefonon tanul (szavazat és olvasási idő alapján).

## Beállítás (egyszer)
1. A munkafolyamat-fájlt `.github/workflows/media-noise.yml` néven hozd létre, majd **Actions › Média-Zaj Twin › Run workflow**.
2. **Settings › Pages**: Deploy from a branch › `main` › `/ (root)`.
3. Értesítéshez (nem kötelező): **Settings › Secrets and variables › Actions › New repository secret**: `NTFY_TOPIC`. Nélküle az értesítés lépése csendben kimarad.

## Fizikai keresztellenőrzés (nem kötelező)
Ha létezik a `data/metrics/environment_truth_matrix.json`, a szerver összeveti vele a hírek állításait:
* a hír anomáliáról szól és a mérés igazolja: **V +0,15**
* a hír katasztrófáról szól, de a mérés nyugodt: **V −0,20 és S +0,15**
* a Nap/geomágneses témák bárhol ellenőrizhetők; a földrengés, vihar, árvíz csak a 250 km-es körzetben (vagy hely nélküli helyi/országos hírnél). 12 óránál régebbi mátrixot nem használ.

Elfogadott alakok (bármelyik): `{"updated":"2026-11-01T11:30:00Z","flags":["geomagnetic"]}`, `{"anomalies":{"earthquake":{"active":true,"magnitude":5.1},"solar":{"class":"M2.1"}}}`, vagy lapos kulcsok: `kp`, `earthquake_max_mag`, `wind_gust_kmh`, `pressure_drop_3h`, `flare_class`.

## Frissítés
A munkafolyamat csak akkor csomagol ki, ha a `.mnt-version` fájl nem `v38`. Újrakicsomagoláshoz: Run workflow › `force_extract = igen` (felülírja a kézi módosításokat).

