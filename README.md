# Média-Zaj Twin (v39)

Vas megye / Alpokalja információs zaj-mérője. **ATM = G · S · (1 − V)**

| Jel | Jelentés | Honnan |
|---|---|---|
| G | fizikai nyugalom (stationarity), 0..1: 1,0 = nyugodt környezet, kicsi = fizikai anomália | az M1 (Solaris) `environment_truth_matrix.json` `core_metrics.stationarity_G` mezője; mérés nélkül 1,0 (feltételezett) |
| S | a hír nyelvi zaja, 0..1 | indulatszavak, felkiáltójel, NAGYBETŰ, csalogató szavak, listás cím, három pont, felsőfok |
| V | érvényesség, 0..1: a hír állításainak egyezése a fizikai méréssel és az ellenőrizhetőség | hivatalos forrás, bizalom, számok/idézet/hivatkozás, több független forrás, fizikai keresztellenőrzés |

Az ATM akkor nagy, ha a fizikai környezet nyugodt (G nagy), a hír hangos (S nagy), és az állításai nem érvényesek (V kicsi).

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
Ha létezik az M1 `data/metrics/environment_truth_matrix.json` fájlja (P8-séma: `header` / `core_metrics` / `dynamic_payload` / `weights_vector`), a szerver összeveti vele a hírek állításait. Az `ANOMALY` státusz aktív napkitörés- és geomágneses anomáliát jelent; a számértékek (Kp ≥ 5, Bz ≤ −10 nT, M/X kitörés, szél ≥ 700 km/s) külön is jelzőt adnak:
* a hír anomáliáról szól és a mérés igazolja: **V +0,15**
* a hír katasztrófáról szól, de a mérés nyugodt: **V −0,20 és S +0,15**
* a Nap/geomágneses témák bárhol ellenőrizhetők; a földrengés, vihar, árvíz csak a 250 km-es körzetben (vagy hely nélküli helyi/országos hírnél). 12 óránál régebbi mátrixot nem használ.

Kimenet a P8-buszra: `data/metrics/media_noise_matrix.json` (`M2_MEDIA_ZAJ`). Az M8 Sentinel a `data/metrics/weights_M2.json` fájllal hangolhatja a súlyokat (`[indulat, csalogatás, bizonyíték, megerősítés]`, 0..2).

Régebbi, laza alakok is elfogadottak: `{"updated":"2026-11-01T11:30:00Z","flags":["geomagnetic"]}`, `{"anomalies":{"earthquake":{"active":true,"magnitude":5.1},"solar":{"class":"M2.1"}}}`, vagy lapos kulcsok: `kp`, `earthquake_max_mag`, `wind_gust_kmh`, `pressure_drop_3h`, `flare_class`.

## Frissítés
A munkafolyamat csak akkor csomagol ki, ha a `.mnt-version` fájl nem `v39`. Újrakicsomagoláshoz: Run workflow › `force_extract = igen` (felülírja a kézi módosításokat).
