# Sklepy: jak działają ich strony i jak dodać kolejny

Notatki techniczne do rozwijania `scrapper.py`. Opisują, skąd skrypt bierze dane w obsługiwanych
sklepach (AliExpress, Allegro) i co już wiadomo o sklepach, których na razie nie ma (TME, Kamami,
Botland, eBay). Stan na listopad 2026: sklepy zmieniają strony, więc przed użyciem warto
sprawdzić, czy opis nadal się zgadza.

## Jak skrypt obsługuje sklep

Każdy sklep to wpis w słowniku `SKLEPY` w `scrapper.py`:

| Klucz | Wymagany | Co robi |
|---|---|---|
| `url_wyszukiwania` | tak | `lambda fraza, strona: url` – adres listy wyników dla frazy i numeru strony (od 1) |
| `link` | tak | wyrażenie regularne wyłapujące linki do ofert z listy wyników (`a[href]`) |
| `normalizuj` | tak | `lambda m: url` – z dopasowania robi jeden stały adres oferty (klucz w cache, bez duplikatów) |
| `start` | tak | strona główna, otwierana przez `--przegladarka` (logowanie, cookies) |
| `parametry` | nie | `(początek, koniec)` – wyrażenia ograniczające blok parametrów w tekście strony; linie w bloku są brane parami *klucz / wartość* |
| `pomin_linie` | nie | wyrażenie: linie w bloku parametrów do pominięcia (np. przyciski) |
| `bez_oceny_listy` | nie | `True`, gdy lista wyników nie pokazuje tytułów; wyłącza wstępną ocenę po tytule |
| `limity` | nie | stałe limity sklepu, np. `{"tempo": 2.5, "max": 15, "strony": 2, "przerwa_co": 5}`; opcje z linii poleceń mogą je tylko zaostrzyć |
| `jezyk` | auto | `en` dla AliExpress, `pl` dla pozostałych; decyduje, czy profil użyje `frazy_pl` |

Poza wpisem w `SKLEPY` trzeba jeszcze dopisać domenę w `sklep_z_url()` (rozpoznaje sklep po adresie).

**Przebieg dla jednej oferty** (funkcja `pobierz_aukcje`):

1. Otwórz stronę. Jeśli jest captcha, poczekaj na użytkownika (`czekaj_na_captche`).
2. **AliExpress:** dane z przechwyconej odpowiedzi API (niżej).
   **Pozostałe sklepy:** `dane_ldjson()`, czyli obiekt `schema.org/Product` z `<script type="application/ld+json">`
   (tytuł, cena, opis) plus `parametry_strony()`: blok z klucza `parametry`, a gdy go nie ma,
   pary z tabel `<table>` i list `<dl>` na stronie.
3. Gdy żadna z metod nie zadziała: cały tekst strony (`dane_ze_strony`). To ostateczność, bo łapie
   polecane i sponsorowane produkty.

Dane trafiają do cache jako tekst z sekcjami `SPECYFIKACJA`, `WARIANTY` i `OPIS`. Ocena traktuje
specyfikację jako pewniejszą od opisu.

**Wykrywanie captchy** (`powod_captchy`): adres strony lub widocznej ramki zawiera coś z
`CAPTCHA_W_URL` albo tekst widocznej ramki zawiera frazę z `CAPTCHA_W_TEKSCIE`. Ramek niewidocznych
nie bierzemy pod uwagę, bo niewidoczna reCAPTCHA jest też na zwykłych stronach.

---

## Obsługiwane

### AliExpress

- **Wyszukiwanie:** `https://www.aliexpress.com/w/wholesale-<fraza-z-myślnikami>.html?page=N`
- **Linki do ofert:** `/item/<id>.html`; normalizowane do `https://www.aliexpress.com/item/<id>.html`.
  Kafelek na liście to jeden `<a>` z tytułem i ceną w środku, więc wstępna ocena po tytule działa.
- **Dane oferty:** strona jest renderowana w przeglądarce (CSR), a sam HTML zawiera tylko szkielet.
  Treść przychodzi z zapytania **`mtop.aliexpress.pdp.pc.query`** (JSONP: `mtopjsonp1({...})`).
  Skrypt przechwytuje odpowiedź przez `page.on("response")` i nie wysyła własnych zapytań.
  Ważne pola w `data.result`:
  - `PRODUCT_TITLE.text`: tytuł
  - `PRODUCT_PROP_PC.showedProps[]`: specyfikacja (`attrName` / `attrValue`, np. `Voltage: 3V`)
  - `SKU.skuProperties[].skuPropertyValues[].propertyValueDisplayName`: warianty (np. „DC3V”)
  - `PRICE.targetSkuPriceInfo.salePriceString`: cena wybranego wariantu. W `skuIdStrPriceInfoMap`
    warianty wyprzedane mają ceny-zaślepki typu 511 581 zł, więc nie brać z niej minimum.
  - `PRICE.productId`: do sprawdzenia, czy odpowiedź dotyczy otwartej oferty
  - `DESC.pcDescUrl`: opis sprzedawcy (HTML na `pdp.aliexpress-media.com`, pobierany osobno).
    Często są w nim same obrazki.
- **Pułapki:** w specyfikacji bywa wpisany tylko przedział kategorii („Napięcie: 0–5 V”, „11-50 V”),
  wybierany przez sprzedawców byle jak.
- **Captcha:** przekierowanie na `…/_____tmd_____/punish?x5secdata=…` z reCAPTCHA (enterprise) w ramce.
  Po rozwiązaniu w stronie zostaje czasem ukryta ramka `punish`, stąd ignorowanie niewidocznych ramek.
  Mniej captchy dostają zalogowani użytkownicy.

### Allegro

- **Wyszukiwanie:** `https://allegro.pl/listing?string=<fraza>&p=N` (ok. 68 ofert na stronę).
- **Linki do ofert** występują w trzech postaciach, wszystkie z numerem oferty:
  - `/produkt/<nazwa>-<uuid>?offerId=<id>` (najczęstsza)
  - `/oferta/<nazwa>-<id>`
  - sponsorowane: `/events/clicks?…&redirect=https%3A%2F%2Fallegro.pl%2Foferta%2F<id>…`

  Normalizowane do `https://allegro.pl/oferta/<id>` (Allegro przekierowuje to na właściwą stronę).
  Linki `/oferty-produktu/…?ocoi=…` (porównanie ofert jednego produktu) są pomijane.
- **Lista wyników:** tytuł jest w `<a>` wewnątrz `<article>`. Skrypt bierze tekst całego `article`.
- **Dane oferty:** JSON-LD `Product` z polami `name`, `description` (czysty tekst opisu),
  `offers.price`, `gtin` i `brand`. Parametry są w tekście strony między `Parametry` a
  `WSZYSTKIE PARAMETRY` lub `Opis`, w parach linii, np. `Rodzaj gwintu` / `E27`, `Barwa światła` / `czerwony`.
- **Pułapki:** reszta strony to sponsorowane i polecane oferty („Propozycje dla Ciebie”,
  „Zamów zestaw…”), które w starej metodzie (cały tekst strony) dawały fałszywe trafienia,
  np. „E27” z polecanej oferty.
- **Captcha:** DataDome (`captcha-delivery.com`) albo reCAPTCHA z tekstem „nie jestem robotem”.
  Pojawia się po kilku do kilkunastu ofertach.
- **Blokada IP:** po ok. 120 ofertach w ok. 4 h (dwa profile naraz, `--tempo 1.5`) Allegro pokazało
  stronę „Zostałeś zablokowany” z adresem IP. Tego nie da się rozwiązać jak captchy. Skrypt
  rozpoznaje ją (`BLOKADA_W_TEKSCIE`), przerywa sklep i zapisuje `dane/blokada_allegro.txt`
  (pomijanie przez 24 h). Stąd stałe `limity` Allegro w `SKLEPY`.

---

## TODO: sklepy sprawdzone, ale niedodane

Konfiguracje poniżej działały w teście (listopad 2026). Żeby włączyć sklep, wklej wpis do
`SKLEPY`, dopisz domenę w `sklep_z_url()` i nazwę sklepu w `sklepy = [...]` profilu.

### TME (tme.eu): hurtownia elektroniczna

**Dlaczego warto:** ma żarówki miniaturowe i sygnalizacyjne (Polam-Elta, np. `LW-E14-24AC/DC`,
`LR-E14-230AC`) z porządną, ustandaryzowaną specyfikacją.

**Dlaczego na razie nie:** Cloudflare jest dość agresywny. Weryfikacja zwykle przechodzi sama po
kilku sekundach (skrypt czeka 10 s bez alarmu), ale nie zawsze.

- **Wyszukiwanie:** `https://www.tme.eu/pl/katalog/?search=<fraza>` przekierowuje na
  `?queryPhrase=<fraza>`. Paginacja `&page=N` jest niesprawdzona.
- **Linki:** `/pl/details/<symbol>/<kategoria>/<producent>/`; normalizowane do `/pl/details/<symbol>/`.
- **Lista wyników:** pokazuje tylko symbole i liczby, bez opisu, więc wstępna ocena po tytule nie
  działa (`bez_oceny_listy`).
- **Strona produktu:** JSON-LD `Product`; `name` = „POLAM-ELTA LW-E14-24AC/DC”,
  `description` = „Lampka LED; E14; biały; 24VDC; 24VAC”. Parametry są w tekście po
  `Specyfikacja` / `Zaznacz wszystkie`, pary linii (np. `Rodzaj trzonka` / `E14`,
  `Napięcie pracy` / `24V AC, 24V DC`), przeplatane liniami „Pokaż produkty podobne (…)”.
  Po przejściu Cloudflare w adresie zostaje `?__cf_chl_rt_tk=…`, więc nie można po nim wykrywać weryfikacji.
- **Alternatywa bez scrapowania:** TME ma oficjalne API (https://developers.tme.eu), darmowe po
  rejestracji. Daje wyszukiwanie i parametry, bez Cloudflare. To lepsza droga niż przeglądarka.
- **Do profili:** TME nazywa to „lampka LED E14”, „żarówka miniaturowa”, więc przydałyby się `frazy_tme`.

```python
"tme": {
    "url_wyszukiwania": lambda fraza, s: (
        f"https://www.tme.eu/pl/katalog/?queryPhrase={quote(fraza)}&page={s}"
    ),
    "link": re.compile(r"tme\.eu/pl/details/([^/?#]+)/"),
    "normalizuj": lambda m: f"https://www.tme.eu/pl/details/{m.group(1)}/",
    "start": "https://www.tme.eu/pl/",
    "parametry": (r"\nSpecyfikacja\n(?:Zaznacz wszystkie\n)?", r"\n(?:Zobacz pozostałe|Dokumentacja|Opis)"),
    "pomin_linie": r"^Pokaż produkty podobne",
    "bez_oceny_listy": True,
},
```

Do `CAPTCHA_W_TEKSCIE` dodano już frazy Cloudflare („verifying you are human”,
„sprawdzanie, czy jesteś człowiekiem”…).

### Kamami (kamami.pl): elektronika, PrestaShop

**Co ma:** mało oświetlenia, ale jest np. „Żarówka LED 3,8V E10” (biała i czerwona, ok. 4 zł),
dobry zamiennik do latarek.

- **Wyszukiwanie:** `https://kamami.pl/szukaj?s=<fraza>&page=N`. Bez blokad. Gdy nic nie
  pasuje, lista jest pusta (np. „żarówka E14”: 0 wyników).
- **Linki:** `/<kategoria>/<id>-<nazwa>.html`. Kategorię `wycofane-z-oferty/` trzeba pomijać
  (produkty wycofane).
- **Strona produktu:** JSON-LD `Product` działa (tytuł, cena, opis). **Parametry nie zostały
  znalezione:** tabele i `<dl>` na stronie były puste. W PrestaShop parametry są zwykle w zakładce
  „Dane techniczne” (`dl.data-sheet`), być może ładowanej po kliknięciu. **TODO:** sprawdzić
  i ewentualnie dodać klucz `parametry`.

```python
"kamami": {
    "url_wyszukiwania": lambda fraza, s: f"https://kamami.pl/szukaj?s={quote_plus(fraza)}&page={s}",
    "link": re.compile(r"(https://kamami\.pl/(?!szukaj|content|module|wycofane-z-oferty/)[\w-]+/\d+-[\w-]+\.html)"),
    "normalizuj": lambda m: m.group(1),
    "start": "https://kamami.pl",
},
```

### Botland (botland.com.pl): elektronika i druk 3D, PrestaShop

**Co ma:** żarówek praktycznie nie ma. Na „żarówka”, „żarówka E14” i „filament LED” zwraca
**te same bestsellery** (drukarki Bambu Lab, sklejka), czyli brak wyników, a zamiast nich polecane
produkty. Filtr `wymagane_tytul` je odrzuca, ale szkoda czasu. Może się przydać do innych
profili (moduły, ładowarki Li-ion, diody).

- **Wyszukiwanie:** `https://botland.com.pl/szukaj?s=<fraza>&page=N`. Bez blokad.
- **Linki:** `/<kategoria>/<id>-<nazwa>-<EAN>.html`.
- **Strona produktu:** JSON-LD `Product` działa (tytuł, opis, cena). Parametry są w zakładce
  „Specyfikacja”. **TODO:** sprawdzić, czy są w `<table>`, i rozpoznawać pustą listę wyników,
  żeby nie zbierać bestsellerów.

```python
"botland": {
    "url_wyszukiwania": lambda fraza, s: f"https://botland.com.pl/szukaj?s={quote_plus(fraza)}&page={s}",
    "link": re.compile(r"(https://botland\.com\.pl/(?!szukaj|content|module)[\w-]+/\d+-[\w-]+\.html)"),
    "normalizuj": lambda m: m.group(1),
    "start": "https://botland.com.pl",
},
```

### eBay: pomysł, nie sprawdzony

- Głównie „Kup teraz” w stałych cenach; aukcje są mniejszością. Dużo sprzedawców z USA i Chin
  (wysyłka, cło) i sporo rzeczy używanych, więc raczej uzupełnienie.
- **Oficjalne Browse API** (https://developer.ebay.com, darmowy klucz). Wyszukiwanie zwraca JSON
  z tytułem, ceną i `itemSpecifics` (np. „Voltage”), bez przeglądarki i bez captchy.
  Wymagałoby osobnej ścieżki w kodzie (zapytania HTTP zamiast Playwright).

## Inne pomysły

- **Rozpoznawanie pustej listy wyników:** sklepy pokazują wtedy bestsellery (Botland) albo
  „podobne” produkty. Można dodać klucz `brak_wynikow` z frazą typu „Brak wyników”.
- **Wykrywanie wariantów na Allegro:** oferty z wyborem wariantu (np. 12 V / 230 V) mają warianty
  poza JSON-LD. Sekcja `WARIANTY` jest dla Allegro na razie pusta.
