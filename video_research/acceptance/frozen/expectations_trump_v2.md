# Trump-vám valós átirat értékelés (v2, YouTube-szöveggel): elvárások TERVEZETE (4. átdolgozás)

ÁLLAPOT: TERVEZET, a felhasználó jóváhagyására vár. Nem lefagyasztott, nem futásengedély. Jóváhagyás után kerül rögzítésre a lenyomat, és csak utána javasolható külön futásjóváhagyás (futásazonosító, modell, kérés-, token- és időkeret). A v1 (3adfa04c…f83a) és kódja érintetlen. Ez a 4. átdolgozás; az 1. tervezet lenyomata: a84b956c28c91df501e6d12a33b2df05cb8a74616547077c85eb78b7828ef463, a 2. átdolgozásé: acd13ea03a58bd8ec414cb81c1dc66eb2245f3b69f36d3bfc92121f27ee6020c, a 3. átdolgozásé: 15f749dc5d1a296f7cc4b5508b683aba58e1d4824aabdc1aa360e434d39dffd4. A változások listája a végén.

## Forrás
YouTube, "The Truth About Trump's Tariffs", video_id AfVGUiet39E (2025-02-18), a KÉZI angol feliratsáv (en-US) utolsó szakasza, 4:09-től a végéig; szegmensidők a hosszú videó abszolút másodpercei. Ez szó szerint megegyezik a Short (VQlVj-X-xFs, 2025-03-04) beszélt szövegével; a képet nem hasonlítottuk össze. Lekérés: 2026-11-21, Firecrawl 'youtube-com' szolgáltató. Uploader-szerkesztett felirat, nem ASR. Importáló szerinti eredet: user_provided_transcript. A bemeneti szöveg SHA-256 (a szegmensek "\n"-nel fűzve): fc8c8a03deb79e8ce8bbd29993559ead6253a09f94119d77a06ab8ca2d87abe5

## Bemenet (szó szerint, SRT-ként, valódi időbélyegekkel)
- 4:09.082 (+2460 ms): In addition to more tariff hikes on China,
- 4:11.542 (+6632 ms): he plans to levy 25% tariffs on everything from Canada and Mexico too.
- 4:18.174 (+8425 ms): These new tariffs would cost the typical American household an additional $1,200 in 2025.
- 4:26.599 (+2336 ms): But if Trump makes good on previous pledges
- 4:28.935 (+2502 ms): to slap tariffs on imports from every country,
- 4:31.437 (+5548 ms): American families can expect to spend as much as $4,000 more.
- 4:36.985 (+3837 ms): Trump has suggested he would use the revenue from tariffs
- 4:40.822 (+4504 ms): to “offset” more tax cuts for the rich and big corporations.
- 4:45.326 (+3921 ms): But of course, as I said, any revenue raised from tariffs
- 4:49.247 (+1835 ms): would be coming out of your pocket.
- 4:51.082 (+4171 ms): The tariffs you pay could help facilitate this massive
- 4:55.253 (+4212 ms): transfer of wealth from most Americans to the super rich.
- 4:59.465 (+4588 ms): So when you’re paying more for groceries, gas, and housing,
- 5:04.053 (+6131 ms): know where your money is really going and know whom to blame.

## Kutatási kérdés
Ki fizeti az új vámokat, és mekkora költséget állít a beszélő az amerikai háztartásokra, milyen feltételekkel?

## Elvárt találatok (a v1 jóváhagyott tartalmi elvárásai, a YouTube-szöveg számírásmódjára igazítva)
- E1: 25%-os vám a Kanadából és Mexikóból érkező árukra, és további emelés Kínára. Terv, nem életbe lépett; hatókör: Kanada és Mexikó felől érkező áruk, nem minden ország.
- E2: tipikus háztartásnak plusz 1200 dollár ("$1,200"). Feltételes ("would cost"), 2025-re, az E1 vámjaira.
- E3: akár 4000 dollár ("$4,000"), ha minden országra vámot vetnek ki. Kettős feltétel: korábbi ígéretek beváltása és felső határ ("as much as"). Külön marad az E2-től; a 2025 nem vihető át ide.
- E4: a vám költségét az amerikaiak viselik. A beszélő állítása; a hosszú videóban szemléltető példa támasztja alá, forrás nélkül.
- E5: Trump a vámbevételt adócsökkentések ellentételezésére javasolta/jelezte. Szándék, nem döntés; az "offset" a forrásban idézőjelben áll.
- L1 (lead ellenőrzésre): honnan van az 1200 és a 4000 dolláros becslés. A szöveg és a videó leírása forrást nem nevez meg. SZIGORÍTÁS (új a v1-hez képest): szerkezetileg akkor teljesül, ha az E2 vagy az E3 helyén van olyan lead, amelyen UGYANAZON a lead-en egyszerre van (a) a modelltől származó, nem üres needs_check (megnevezett hiányzó ellenőrzés) ÉS (b) a modelltől származó ellenőrzési kérdés. Önmagában nem elég: a "But…" következő mondat miatt automatikusan képzett minősítő-nyom; a fordítás hiánya miatt automatikusan képzett nyom; a részleges relevancia ("csak részben releváns"); az általános "a modell ellenőrizendő nyomként jelölte" indok; és az, ha csak az ok vagy csak a kérdés a modellé. A kérdés tartalmi megfelelése (valóban a becslés forrására/módszerére irányul-e) emberi megítélés.

Az E1-E5 vödre (keep vagy lead) nem előírt: mindkettő elfogadott, a kihagyás (szűrési napló) hiány. Megfigyelés: az E2 és az E5 mondatát "But…" kezdetű sor követi, ezért a rendszer ezeket magától lead-re teheti.

## Zaj (nem lehet önálló találat)
Az értékelő zárlat ("massive transfer of wealth from most Americans to the super rich", "know where your money is really going and know whom to blame"): legfeljebb a beszélő megítélésének jelölt minősítő. (Nincs fejléc, nincs levágott vég.)

## Csapdák (hibának számít)
- a vám tényként, életbe lépettként szerepel;
- az 1200 és a 4000 összevonva, vagy a 4000 feltétel nélkül;
- az "in 2025", a "typical household" vagy a feltételes mód elvész;
- a 2025 átvitele az E3-ra (az E3 idézetében nincs): TARTALMI HIBA, emberi elbírálással; a kemény kapuk (hard_ok) ezt nem fogják meg, a kiértékelő `content_flags` mezőben jelzi;
- az E1 általánosítása minden országra;
- bármi verified vagy külső igazolás jelzéssel jelenik meg;
- a "vagyonátadás" tényként a találatok között;
- olyan idézet, amely nincs a szövegben; hibás időbélyeg (lásd Időbélyeg-szabály: kemény kapu).

## Értékelés
Automatikus kapuk (kemény): megvan-e az elvárt tétel az idézet kifejezéseivel, az idézet és a forráskapcsolat valódi-e, az időbélyeg helyes-e (lásd Időbélyeg-szabály), nincs ellenőrzött jelzés, az E2 és E3 nincs egy állításba vonva, az E1 nincs általánosítva, zaj nem önálló találat, a nyom kérdéssel jár, az L1 szerkezeti kapuja (lásd L1 fent és L1: mi automatikus és mi emberi). Szinonimalistás és heurisztikus segédjelzések (nem kemény kapuk, nem ítéletek): feltétel, hatókör, időpont, állítás-jelleg, a kérdés forrásra utalása, az állítás számai az idézetben vannak-e (lásd Számátvitel-jelzés). A tartalmi megfelelés (jelentés, hatókör, feltétel) emberi megítélés; a modell saját kivonata nem lehet az egyetlen alap; az elvárásokat a futás eredménye alapján nem módosítjuk. A kiértékelő sosem mond ki "megfelelt" tartalmi ítéletet.

## Időbélyeg-szabály
A hivatkozás időbélyegének az idézetet tartalmazó legkisebb egymást követő szegmenssorozat első szegmensének kezdetével kell egyeznie (másodpercben, ±0,0015 s). Ha az idézet szegmens közepén kezdődik, a szegmens kezdete az elvárt időbélyeg; a pontosság tehát szegmensszintű (a szegmensek itt 1,8–8,4 s hosszúak). Több szegmensen átívelő idézetnél a sorozat első szegmense számít. A minősítő-hivatkozás (a következő "But…" sor) külön hivatkozás, a saját szegmensének kezdetével. Ha az idézet nem található, az időbélyeg-kapu kihagyja, mert a hiányzó idézetet az idézet-kapu jelzi. (Az ablakhossz és az ismétlődő idézet kezelése megvalósítási korlát, nem elvi követelmény: lásd Megvalósítási korlátok.)

## Számátvitel-jelzés
Ha egy találat állításának számjegyes száma (pl. 2025) az idézetekben nem szerepel, segédjelzés kerül a felülvizsgálati lapra. Ez nem kemény kapu: önmagában nem okoz bukást, a hard_ok értékét nem befolyásolja. Csak számjegyes számokat néz (a "négyezer" típusú szóbeli számokat nem). Pontosan mely idézeteket vizsgálja: a találat MINDEN hivatkozásának idézetét, vagyis a fő (support) ÉS a minősítő (qualifier) hivatkozásokét is; az állítás számjegyes számait ezeknek az idézeteknek a számjegyes számaiból képzett UNIÓVAL veti össze. Következmény: ha egy szám csak a minősítő-hivatkozás idézetében szerepel, nem jelzi. Az E3-ra vonatkozó 2025-ös tartalmi jelzés ugyanezt az uniót használja. TARTALMI MINŐSÍTÉS: a 2025 jogosulatlan átvitele az E3-ra tartalmi hiba akkor is, ha a hard_ok igaz. A kiértékelő ezt a `content_flags` mezőben, az E3 sor jelzésében és a `human_content_judgement` szövegében ("TARTALMI HIBA GYANÚ") külön megjelöli, és emberi elbírálást kér; a tartalmi ítéletet nem mondja ki.
Korlát: mivel a számátvitel-jelzés a fő és a minősítő idézetek számainak unióját vizsgálja, egy kizárólag a minősítő-hivatkozás idézetében szereplő 2025 elnyomhatja az E3-ra vonatkozó figyelmeztetést (és a content_flags jelzést). Ez nem teszi tartalmilag elfogadhatóvá a 2025 jogosulatlan átvitelét az E3-ra: azt a felülvizsgálatnál az E3 állítását az E3 saját idézetével összevetve embernek kell ellenőriznie, a jelzés hiányától függetlenül.

## L1: mi automatikus és mi emberi
Automatikus (kemény): az L1 fent leírt szerkezeti kapuja. A kapu mind az okot, mind a kérdést .strip() után vizsgálja: az üres vagy csak szóközös ok, illetve kérdés nem számít modelltől származónak, és a vezető szóközös automatikus szöveg is automatikusnak számít. (A pipeline is levágja a szóközt a needs_check-en és a kérdésen, és üres needs_check-et nem vesz fel okként; a kiértékelő ezt függetlenül is megköveteli.) Modelltől származónak az az ok számít (tiltólistás eredetbecslés), amely nem a pipeline négy rögzített szövegének valamelyikével kezdődik (a "But…" miatti minősítő; a fordítás hiánya; "csak részben releváns a kérdéshez"; "a modell ellenőrizendő nyomként jelölte"): a megmaradó ok a modell needs_check szövege. A kérdés akkor modellé, ha nem a "Módosítja-e vagy cáfolja-e az állítást a következő mondat…" vagy a "Mi a magyar tartalma ennek az idézetnek…" automatikus kérdés. Emberi: hogy a kérdés ténylegesen a becslés forrására vagy módszerére irányul-e. A jelzőszavas találat (forrás, honnan, ki számol, módszer, alapul) csak segédjelzés: megléte nem bizonyítja a megfelelést, hiánya nem bukás. A lista téves pozitívot (pl. "Honnan tudjuk, hogy 2025-re szól?") és téves negatívot (pl. "Számolta ki valaki ezt?") is ad.

## Megvalósítási korlátok
- Hatszegmenses keresési ablak (megvalósítási korlát, nem elvi követelmény): a pipeline (locate_quote) és az időbélyeg-ellenőrzés legfeljebb 6 egymást követő szegmensből álló idézetet old fel; ennél hosszabb idézetet a pipeline nem fogad el (nem ellenőrizhető idézet), így az nem kaphat időbélyeget.
- Ismétlődő idézet: a jelenlegi ellenőrzés mindig az idézet ELSŐ előfordulásának szegmenséhez tartozó kezdetet várja el, ezért egy helyes, de későbbi előfordulásra mutató hivatkozást is hibás időbélyegként utasíthat el (téves bukás). Ebben a szövegben nincs ilyen idézet, ezért jelenleg nem érint tételt.
- Szegmensszintű időbélyeg-pontosság (nem szószintű).
- Az L1 automatikus elemeinek kizárása tiltólistás eredetbecslés, amely a pipeline (extraction.py) üzenetszövegeire épül; a pipeline nem ad szerkezeti eredetjelzőt, ezért ez NEM kimerítő eredetbizonyítás. Dokumentált regressziós védőháló: a tesztek ellenőrzik, hogy a négy rögzített szöveg a forrásban megvan, és az ok-képzési helyek száma (jelenleg 5) nem változott. Ez csak a változást jelzi; azt nem bizonyítja, hogy minden jövőbeli ok-típust helyesen osztályozunk. Egy új automatikus ok-típust a számossági teszt jelezné, de addig a kiértékelő modelltől származónak venné. Ha a modell needs_check-je szó szerint egy rögzített szöveggel kezdődne, megnevezett ellenőrzésnek nem számítana.
- A számátvitel-jelzés csak számjegyes számokat néz.
- A jelzőszólista szóalapú (részszöveges illesztés), tévesen pozitív és tévesen negatív találata is lehet.

## Ismert korlátok
A kifejezés-alapú lefedettség nem az állítás helyességét mutatja. A "kemény" kapuk közül a hatókör-kapu szóalapú (a v1-ben); az L1 kérdésének tartalmi megfelelését nem automatizáljuk. Lásd még: Megvalósítási korlátok.

## Nem része, és nem történik
Modellhívás; futás; a vezérlő bekötése; a CLAUDE.md módosítása; commit (külön engedély kell); a TikTok-felirat lekérése.

## Változások
A) Az 1. tervezethez képest (a84b956c…ef463 → ez a változat):
- L1: a modelltől származó, nem üres needs_check ÉS kérdés kell ugyanazon a lead-en; a fordítás-hiány, a részleges relevancia és az általános nyomjelölés nem elég; csak az ok vagy csak a kérdés sem (K3a+K4). Elfogadási feltételt módosít.
- Új szakaszok: Időbélyeg-szabály (K1), Számátvitel-jelzés (K2), L1: mi automatikus és mi emberi (K3b), Megvalósítási korlátok. Ezek pontosítások.
- A 2025 átvitele az E3-ra már az 1. tervezetben is tiltott volt (csapdalista; az E3 sorában: "a 2025 nem vihető át ide"). Nem új tilalom: az új elem az egyértelműbb dokumentálás (tartalmi hiba, a hard_ok-tól függetlenül) és a `content_flags` jelzés.
- A jelzőszólista a v2-ben szűkített (a "becslés" és a "számít" kivéve); a lista továbbra is csak segédjelzés.
B) A 2. átdolgozáshoz képest (acd13ea0…020c, a 3. átdolgozás):
- Az L1-kapu az okot és a kérdést is .strip() után vizsgálja (üres és csak szóközös nem elég); a pipeline-garancia és a kiértékelő-oldali ellenőrzés külön dokumentálva.
- A számátvitel-jelzés vizsgált idézetei pontosítva: fő ÉS minősítő hivatkozások uniója.
- Az időbélyeg-szabályból a "legfeljebb 6" kikerült elvi követelményként; megvalósítási korlát maradt. Az ismétlődő idézetnél leírva, hogy egy helyes, későbbi előfordulásra mutató hivatkozást is elutasíthat.
- Az ok-képzési helyek számlálása nem kimerítő eredetbizonyítás, hanem dokumentált regressziós védőháló a tiltólistás eredetbecslés korlátaival.
C) A 3. átdolgozáshoz képest (15f749dc…ffd4, ez a 4. átdolgozás):
- Számátvitel-jelzés: kifejezett korlát-mondat arról, hogy a fő és a minősítő idézetek uniója miatt egy kizárólag a minősítő-hivatkozás idézetében szereplő 2025 elnyomhatja az E3-ra vonatkozó figyelmeztetést (és a content_flags jelzést), és hogy ez nem teszi elfogadhatóvá az évszám jogosulatlan átvitelét; azt embernek kell ellenőriznie. Kizárólag dokumentációs pontosítás: a kód, a tesztek és az elfogadási feltételek változatlanok.
