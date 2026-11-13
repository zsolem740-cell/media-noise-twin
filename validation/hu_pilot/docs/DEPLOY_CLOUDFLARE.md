# Pilot telepítése Cloudflare Pages-re (közvetlen feltöltés)

Ezt neked kell elvégezned, a modul nem telepít. A Cloudflare menüneveit **nem tudtam a dokumentációból ellenőrizni** (a gép nem érte el a developers.cloudflare.com oldalt), ezért az alábbi lépések általános ismeretre épülnek: ha a felület mást ír, a Cloudflare saját „Direct Upload” útmutatója az irányadó.

## Amit kapsz
- `mz_pilot_stage1.zip`: a v47.10 alkalmazás (változatlanul) + a 20 horgony-cím.
- `mz_pilot_stage2.zip`: ugyanaz az alkalmazás + a 30 mérési cím. **Csak a horgonykör és a megbeszélés után tedd fel.**
- (Később) `mz_pilot_stage3.zip`: csak az eltérő mérési címek, a harmadik szavazathoz.
- Minden zip gyökerében az `index.html` van, mellette `atm_history.json` (a szakasz feedje), `_headers`, `robots.txt`. A zip determinisztikus: a SHA-256 értéke a `stageN_manifest.json`-ban és a jelentésben van; feltöltés előtt hasonlítsd össze.
- Az alkalmazás kódja bájtra azonos a `claude/szavazonkenti-tarolas` ág `public/` mappájával (commit: 682f44b). Kulcs, token, valódi hírmentés, pontszám vagy forrásnév nincs benne.

## Egyszeri beállítás
1. Cloudflare irányítópult → **Workers & Pages** → új **Pages** projekt → **Direct Upload / Upload assets** (feltöltés, nem Git-összekötés).
2. Projektnév: semleges és nehezen kitalálható (például `mz-pilot-` + véletlen betűk). Az URL lesz: `<projektnév>.pages.dev`.
3. Töltsd fel a `mz_pilot_stage1.zip`-et (vagy a kicsomagolt mappát), és telepítsd **Production** környezetbe.
4. **Csak a projekt fő URL-jét** (`<projektnév>.pages.dev`) használjátok. Minden egyes telepítésnek külön, véletlen URL-je is lehet (előnézeti cím): az **másik origin**, és a böngésző tárolója (a szavazatok!) origin szerint külön van. Aki ott szavaz, annak a szavazatai nem lesznek meg a fő URL-en.

## Ellenőrzés telepítés után
- Nyisd meg a fő URL-t telefonon: a fejlécben `v47.10` látszik, a „Gyorsszavazás” a 20 horgonyt kínálja.
- A `_headers` fájl beállításai (a feed ne gyorsítótárazódjon, a lap ne legyen indexelhető): ellenőrizd böngésző fejlesztői eszközeivel, hogy az `atm_history.json` válasza `Cache-Control: no-store`, és a lapé `X-Robots-Tag: noindex`. Ha nem érvényesül, a szakaszváltás előtt töröld a gyorsítótárat a próbaeszközön, és szólj.
- Ne hozz létre Git-összekötést, ne adj meg API-kulcsot.

## Szakaszváltás (ugyanabban a projektben, ugyanaz az origin)
1. A horgonykör és a megbeszélés után töltsd fel a `mz_pilot_stage2.zip`-et **új Production telepítésként ugyanabba a projektbe**.
2. A szavazók frissítsék az oldalt (húzás lefelé vagy újratöltés). A korábbi szavazatok megmaradnak (ugyanaz az origin), az alkalmazás a már szavazott címeket kihagyja.
3. A harmadik szakasz ugyanígy: a `mz_pilot_stage3.zip` csak az `analyze`/`adjudication` parancsok után készül.
Visszaállás: töltsd fel újra az előző zipet.

## A pilot után
Mentsd el az összes szavazó exportját (lásd a szavazói útmutatót), utána töröld a projektet vagy a telepítéseket. A szavazatok csak az eszközökön voltak, a Cloudflare-nél nincs szavazói adat.

## Tudnivalók
- A cím-szövegek nyilvános hírcímek, de a feed a projekt URL-jén bárkinek elérhető, aki tudja a címet. Ha ez nem elfogadható, korlátozd a Cloudflare Access-szel (külön beállítás), vagy használd csak rövid ideig.
- A termelési app (v47.9) adatait ez nem érinti: más origin, más tároló.
