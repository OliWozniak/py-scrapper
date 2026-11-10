# py-scrapper: szukacz aukcji AliExpress / Allegro

**🇵🇱 Polski** · [🇬🇧 English version below](#english)

Skrypt przeszukuje AliExpress (lub Allegro) według podanych fraz, otwiera każdą znalezioną aukcję
i **ocenia ją punktowo** według Twoich reguł, np. „+6 za napięcie 3 V w specyfikacji, −5 za 230 V”.
Wynik to raport HTML/CSV posortowany od najlepszych trafień. Przy każdej aukcji są fragmenty tekstu,
za które dostała punkty, więc szybko sprawdzisz trafienie bez otwierania aukcji.

Czego szukać, definiujesz w pliku [`profile.toml`](profile.toml). Wbudowane przykłady szukają
żarówek E14 na 3–6 V, filamentów LED 3 V i czerwonych żarówek E27 na 12 V, ale w ten sam sposób opiszesz dowolny inny produkt
(zobacz [Edycja profile.toml](#edycja-profiletoml)).

## Spis treści

- [Jak to działa](#jak-to-działa)
- [Instalacja](#instalacja)
- [Pierwsze uruchomienie](#pierwsze-uruchomienie)
- [Captcha](#captcha)
- [Codzienne użycie](#codzienne-użycie)
- [Wszystkie opcje](#wszystkie-opcje)
- [Edycja profile.toml](#edycja-profiletoml)
- [Pliki w katalogu](#pliki-w-katalogu)
- [Rozwiązywanie problemów](#rozwiązywanie-problemów)

## Jak to działa

1. **Zbieranie linków.** Skrypt otwiera prawdziwe okno przeglądarki Chromium (przez Playwright),
   wpisuje każdą frazę z profilu w wyszukiwarkę sklepu i zbiera linki do aukcji z kilku stron wyników.
2. **Wstępna ocena po tytule.** Tytuł każdej aukcji z listy wyników jest oceniany punktami `tytul`
   z reguł, **zanim** aukcja zostanie otwarta. Aukcje poniżej `--prog-listy` (domyślnie 0 pkt, czyli np.
   z „220V” w tytule) są pomijane, a najbardziej obiecujące otwierane jako pierwsze. Oszczędza to czas
   i captche, bo wyszukiwarka AliExpress i tak zwraca głównie żarówki 230 V.
3. **Pobieranie aukcji.** Otwiera kolejne aukcje.
   - **AliExpress:** przechwytuje dane, które strona i tak pobiera ze swojego API: tytuł,
     specyfikację (np. `Voltage: 3V`), warianty, cenę i opis sprzedawcy. Nie ma w nich reklam ani
     poleconych produktów, więc dane są czyste.
   - **Allegro:** tytuł, cenę i opis bierze z danych produktu zapisanych w stronie (JSON-LD),
     a parametry (np. „Rodzaj gwintu”, „Barwa światła”) z sekcji „Parametry”. Polecane i
     sponsorowane oferty nie są czytane.
   - Gdy tych danych nie ma, skrypt czyta tekst całej strony, co jest mniej dokładne.
4. **Ocena.** Każda reguła z profilu sprawdza tytuł, specyfikację i opis, po czym przyznaje lub
   odejmuje punkty.
5. **Raport.** Wyniki ze wszystkich sklepów trafiają do jednego raportu `wyniki_<profil>.html`
   i `.csv`, z kolumną „Sklep”, więc łatwo porównać ceny. Raport odświeża się po każdej aukcji, więc możesz go mieć otwartego w przeglądarce i odświeżać w trakcie.

Pobrane aukcje zapisują się w `dane/cache_<profil>_<sklep>.json`, osobno dla każdego profilu i sklepu.
Kolejne uruchomienia nie pobierają ich drugi raz, a po zmianie reguł możesz przeliczyć oceny bez
internetu (`--tylko-ocena`). Do zapisanego profilu możesz wrócić choćby po miesiącach:
`--lista` pokazuje, ile aukcji ma każdy profil i kiedy był ostatnio uruchamiany.

## Instalacja

Potrzebny jest **Python 3.11 lub nowszy** (dla wbudowanego modułu `tomllib`) oraz biblioteka
**Playwright** z przeglądarką Chromium. Innych zależności nie ma.

### Arch Linux

```bash
sudo pacman -S python-playwright
python -m playwright install chromium
```

### Inne systemy (Debian/Ubuntu, Fedora, macOS, Windows): wirtualne środowisko

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install playwright
python -m playwright install chromium
```

Przy każdym kolejnym uruchomieniu najpierw aktywuj środowisko (`source .venv/bin/activate`).

> `python -m playwright install chromium` pobiera przeglądarkę do `~/.cache/ms-playwright`
> (ok. 150 MB) i nie wymaga uprawnień administratora. Na Debianie/Ubuntu, jeśli przeglądarka
> nie startuje z powodu brakujących bibliotek, uruchom `sudo python -m playwright install-deps chromium`.

Sprawdzenie, czy wszystko działa (to polecenie nie łączy się z internetem):

```bash
python scrapper.py --lista
```

Powinna się pojawić lista profili z `profile.toml`.

## Pierwsze uruchomienie

**1. Przygotuj profil przeglądarki (zalecane).** Otwórz okno przeglądarki, którego będzie używał skrypt:

```bash
python scrapper.py --przegladarka
```

W oknie zaakceptuj cookies i najlepiej **zaloguj się na AliExpress**. Zalogowany użytkownik
dostaje dużo mniej captchy. Gotowe? Wróć do terminala i naciśnij Enter. Sesja zapisuje się w katalogu
`profil-przegladarki/` i zostaje na kolejne uruchomienia. Otwierają się wszystkie sklepy z profilu.

**2. Zrób małe próbne wyszukiwanie:**

```bash
python scrapper.py --strony 1 --max 10
```

Skrypt otworzy okno przeglądarki (zostaw je w spokoju, możesz je zminimalizować) i będzie wypisywał
postęp w terminalu. Po każdej aukcji zobaczysz podgląd oceny:

```
[3/10] https://www.aliexpress.com/item/1005010775885139.html
   · ocena +0  83,68zł  Żarówki LED C35 E14 3W, spiralne żarówki do kandelabrów, 220V…
     kształt C35 / świeczka w tytule (+2); filament / COG w tytule (+2); zasilanie 230 V w tytule (-5)
     [zasilanie 230 V · spec] Napięcie: 220-240 V
```

Znaczki: **★** to mocne trafienie (≥ 8 pkt), **+** trafi do raportu, **·** jest poniżej progu,
a **✗** odpada (brak wymaganego słowa).

**3. Otwórz raport** `wyniki_zarowka.html` w przeglądarce. Zielone wiersze to mocne trafienia,
żółte są do sprawdzenia.

Działa? Uruchom pełne wyszukiwanie: `python scrapper.py`.

## Captcha

Sklepy nie lubią automatycznego przeglądania i co jakiś czas pokazują weryfikację „nie jestem robotem”.
Skrypt sam ją wykrywa: odtwarza dźwięk systemowy, pokazuje powiadomienie na pulpicie
(na Linuksie przez `paplay`/`pw-play` i `notify-send`), wypisuje komunikat i **czeka**.
Dźwięk powtarza się co 30 s przez pierwsze 3 minuty. `--cicho` wyłącza dźwięk i powiadomienia.

- **Rozwiąż captchę w oknie przeglądarki.** Skrypt sam ruszy dalej, gdy weryfikacja zniknie.
- **Albo wpisz polecenie w terminalu:**
  - sam **Enter**: „już rozwiązane, jedź dalej”,
  - **`p`** + Enter: pomiń tę aukcję,
  - **`k`** + Enter: zakończ i zrób raport z tego, co już pobrane.
- **Limit czasu:** po 10 minutach bez rozwiązania aukcja jest pomijana automatycznie.
- **Ctrl+C:** w każdej chwili przerywa wyszukiwanie i robi raport z tego, co już pobrane.

Jak ograniczyć liczbę captchy:

- **Zaloguj się:** użyj `--przegladarka`, jak w kroku 1 powyżej.
- **Zwolnij:** `--tempo 2` podwaja wszystkie przerwy, a `--przerwa-co 8` dodaje dłuższą przerwę
  (1–2,5 min) co 8 aukcji. Każda captcha i tak automatycznie spowalnia dalsze pobieranie.
- **Pobieraj mniej naraz:** ustaw mniejsze `--max`. Cache sprawia, że kolejne uruchomienie
  zaczyna od aukcji jeszcze niepobranych.
- **Użyj zwykłej przeglądarki:** systemowy Chromium zamiast wersji testowej Playwrighta
  (`--chrome /usr/bin/chromium`, na Archu po `sudo pacman -S chromium`). reCAPTCHA zwykle ocenia go lepiej.

## Codzienne użycie

```bash
python scrapper.py --lista                          # jakie są profile
python scrapper.py                                  # pierwszy profil, sklepy z jego pola 'sklepy'
python scrapper.py --profil filament                # inny profil
python scrapper.py --profil filament --sklep allegro          # tylko jeden sklep
python scrapper.py --profil zarowka --sklep aliexpress allegro # wybrane sklepy
python scrapper.py --profil zarowka --sklep wszystkie         # wszystkie obsługiwane sklepy
python scrapper.py --frazy "E14 3V candle" "C35 DC3V"   # własne frazy, reguły z profilu
python scrapper.py --tylko-ocena                    # przelicz raport po zmianie reguł (bez internetu)
python scrapper.py --tylko-ocena --min-ocena -50    # pokaż w raporcie prawie wszystko
python scrapper.py --odswiez --max 60               # pobierz ponownie stare wpisy (patrz niżej)
```

**Jednorazowe wyszukiwanie bez edycji pliku.** Gdy podasz `--wymagane`, `--plus` lub `--minus`, skrypt
tworzy tymczasowy profil `wlasny`. Za wzorce z `--plus` daje +3 (tytuł/specyfikacja) albo +1 (opis),
a za wzorce z `--minus` −5 albo −2:

```bash
python scrapper.py --frazy "TP4056 type-c" "18650 charger module" \
    --wymagane "TP4056|IP2312" --plus "type-?c" "protect" --minus "micro ?usb"
```

**Kilka wyszukiwań naraz.** Każdy profil i sklep ma własny cache i własną kopię przeglądarki
w `dane/`, więc możesz uruchomić kilka skryptów w osobnych terminalach:

```bash
python scrapper.py --profil zarowka                       # terminal 1
python scrapper.py --profil czerwona_e27_12v --sklep allegro   # terminal 2
```

Kopia przeglądarki powstaje przy pierwszym uruchomieniu profilu z głównego `profil-przegladarki/`
(tego z `--przegladarka`), więc zalogowanie przechodzi. Ten sam profil i sklep naraz w dwóch
terminalach się nie uruchomi. Każde okno to osobne zapytania z tego samego adresu IP, więc przy
kilku naraz captcha może pojawiać się częściej. Wtedy pomoże `--tempo 2`.

**`--odswiez`** dotyczy wpisów z cache pobranych starszą wersją skryptu (z tekstu całej strony,
razem z reklamami innych produktów). Takie wpisy z AliExpress są pomijane w raporcie, bo nie da się
ich wiarygodnie ocenić. Skrypt podaje na końcu, ile ich jest. `--odswiez` pobiera je ponownie, już przez API.

## Wszystkie opcje

| Opcja | Domyślnie | Opis |
|---|---|---|
| `--profil NAZWA` | pierwszy w pliku | profil z `profile.toml` |
| `--sklep S …` | z profilu | sklep(y): `aliexpress`, `allegro` albo `wszystkie`; bez tej opcji sklepy z pola `sklepy` profilu (a gdy go nie ma, `aliexpress`) |
| `--lista` | | pokaż profile i zakończ |
| `--frazy F1 F2 …` | z profilu | własne frazy wyszukiwania |
| `--wymagane`, `--plus`, `--minus` | | jednorazowy profil z linii poleceń |
| `--strony N` | 2 | ile stron wyników na każdą frazę |
| `--max N` | 40 | ile najwyżej aukcji otworzyć w tym uruchomieniu (w każdym sklepie) |
| `--prog-listy N` | 0 | otwieraj tylko aukcje, których tytuł na liście wyników ma ≥ N pkt; `-99` = wszystkie |
| `--min-ocena N` | 3 | aukcje z niższą oceną nie trafiają do raportu |
| `--tempo X` | 1.0 | mnożnik przerw (2 = dwa razy wolniej) |
| `--przerwa-co N` | 12 | co ile aukcji dłuższa przerwa; 0 = wyłącz |
| `--odswiez` | | pobierz ponownie stare wpisy AliExpress z cache |
| `--tylko-ocena` | | nic nie pobieraj, tylko przelicz raport z cache |
| `--przegladarka` | | tylko otwórz okno (logowanie, cookies) |
| `--chrome ŚCIEŻKA` | | użyj innej przeglądarki, np. `/usr/bin/chromium` |
| `--cicho` | | bez dźwięku i powiadomień przy captchy |
| `--headless` | | bez okna; captchy nie da się wtedy rozwiązać, niezalecane |

---

## Edycja profile.toml

Plik [`profile.toml`](profile.toml) mówi skryptowi **czego szukać** i **jak oceniać** znalezione aukcje.
Jeden profil to jeden produkt. Możesz mieć ich dowolnie wiele i wybierać je opcją `--profil`.

### Budowa pliku

```toml
[wzorce]                     # (opcjonalnie) wspólne kawałki wzorców, używane jako @NAZWA
NISKIE_V = '...'

[profile.zarowka]            # profil o nazwie "zarowka"  →  --profil zarowka
opis = "..."
frazy = [ ... ]
wymagane = [ ... ]
reguly = [ ... ]

[profile.filament]           # kolejny profil
...
```

Nazwa profilu to tekst po `profile.`. Używaj liter bez polskich znaków, cyfr i `_`, np.
`[profile.ladowarka_usbc]`. Pierwszy profil w pliku jest domyślny.

### Pola profilu

| Pole | Wymagane | Co to jest |
|---|---|---|
| `opis` | nie | krótki opis, pokazywany w `--lista` i w nagłówku raportu |
| `frazy` | tak | lista fraz wpisywanych w wyszukiwarkę sklepu; każda jest szukana osobno |
| `frazy_pl` | nie | frazy po polsku dla polskich sklepów (Allegro); AliExpress używa `frazy` |
| `frazy_<sklep>` | nie | frazy tylko dla jednego sklepu, np. `frazy_allegro`; kolejność: `frazy_<sklep>` → `frazy_pl` → `frazy` |
| `sklepy` | nie | w których sklepach szukać, gdy nie podasz `--sklep`, np. `["aliexpress", "allegro"]` |
| `wymagane` | nie | lista wzorców, które aukcja **musi** zawierać (każdy z nich), inaczej od razu odpada |
| `wymagane_tytul` | nie | wzorce, które musi mieć już **tytuł na liście wyników**, żeby aukcja w ogóle została otwarta, np. gwint `'\bE[\s-]?27\b'`; oszczędza czas i captche |
| `reguly` | tak | lista reguł punktowych, opisanych niżej |

**Frazy** to zwykły tekst, taki jak wpisałbyś w wyszukiwarkę. Na AliExpress lepiej działają frazy
po angielsku (sprzedawcy tak opisują produkty), na Allegro po polsku. Kilka różnych fraz daje więcej
różnych aukcji. Każda fraza × `--strony` to osobne strony wyników do przejrzenia.

**Wymagane** to szybki filtr. Na przykład `wymagane = ['\bE[\s-]?14\b']` odrzuca wszystko,
co nigdzie nie wspomina o gwincie E14. Wzorce są sprawdzane w tytule, specyfikacji i opisie łącznie.

### Reguły

Każda reguła to jedna linia w nawiasach klamrowych:

```toml
reguly = [
    { nazwa = "napięcie 3–4,2 V", wzorzec = '@NISKIE_V', tytul = 6, spec = 6, opis = 2, cytuj = true },
    { nazwa = "filament / COG",   wzorzec = 'filament|\bCOG\b', tytul = 2, opis = 1 },
]
```

| Pole | Domyślnie | Znaczenie |
|---|---|---|
| `nazwa` | (wymagane) | opis reguły widoczny w raporcie i w terminalu |
| `wzorzec` | (wymagane) | czego szukać: zwykłe słowo albo wyrażenie regularne (wielkość liter bez znaczenia) |
| `tytul` | 0 | punkty, gdy wzorzec jest **w tytule** aukcji |
| `spec` | = `tytul` | punkty, gdy jest **w specyfikacji lub wariantach** (np. `Voltage: 3V`, przycisk wariantu „DC3V”) |
| `opis` | 0 | punkty, gdy jest **tylko w opisie** sprzedawcy |
| `cytuj` | `false` | `true` = pokaż w raporcie linie z trafieniem, do szybkiej weryfikacji wzrokiem |
| `chyba_ze` | brak | wzorzec-wyjątek: jeśli pasuje **w tym samym miejscu** co `wzorzec`, reguła się nie liczy |

**Jak liczone są punkty:**

- **Wyjątki (`chyba_ze`).** Aukcje z wariantami piszą np. „110V 220V 12V 24V” w jednym tytule.
  Kara za 230 V odrzuciłaby wtedy także wariant 12 V. Dlatego reguła 230 V ma
  `chyba_ze = '@NISKIE_V|@NISKIE_12'`: jeśli w tym samym miejscu jest też niskie napięcie, kara
  się nie liczy (w raporcie widać „pominięte, są też inne warianty”).
- **Wstępna ocena po tytule:** na liście wyników skrypt widzi tylko tytuł, więc liczą się wyłącznie
  punkty `tytul`. Wyraźna kara w `tytul` (np. −8 za 230 V) odfiltrowuje takie aukcje, zanim zostaną otwarte.
- **Liczy się tylko najpewniejsze miejsce trafienia:** tytuł, potem specyfikacja, potem opis.
  Jeśli „3V” jest i w tytule, i w opisie, reguła daje tylko punkty `tytul`, a nie sumę.
- **Ujemne punkty to kara.** Do oceny aukcji wchodzą wszystkie reguły naraz: aukcja z „3V”
  w opisie (+2) i „220V” w specyfikacji (−5) dostaje razem −3.
- **Ocenę końcową sumuje się ze wszystkich reguł.** W raporcie ≥ 8 pkt to zielony wiersz, a ≥ 4 żółty.
  Dobierz punkty tak, żeby idealna aukcja miała 8 lub więcej, a zwykłe trafienie „po słowach” mniej.
- **Opis sprzedawcy jest najmniej wiarygodny**, bo często wymienia wszystkie możliwe warianty
  i napięcia naraz. Dawaj mu mniej punktów niż tytułowi i specyfikacji.
- **Przedziały kategorii AliExpress** (np. „Napięcie: 0–5 V”, „11-50 V”) sprzedawcy wybierają z listy,
  często byle jak. Traktuj je jako słabą wskazówkę (mało punktów, tylko `spec`) i nie używaj w `chyba_ze`.

### Wzorce: jak pisać

Wzorzec to [wyrażenie regularne Pythona](https://docs.python.org/3/library/re.html), ale na początek
wystarczą zwykłe słowa. Wielkość liter nie ma znaczenia.

| Chcesz znaleźć | Wzorzec | Uwagi |
|---|---|---|
| słowo „filament” | `'filament'` | trafi też „filamentowa” |
| jedno z kilku słów | `'candle\|świecz\|kerze'` | `\|` znaczy „albo” |
| całe słowo „COG” | `'\bCOG\b'` | `\b` to granica słowa, więc nie trafi w „COGNAC” |
| E14, E-14, E 14 | `'\bE[\s-]?14\b'` | `[\s-]?` to opcjonalna spacja lub myślnik |
| C35 albo C37 | `'\bC3[57]\b'` | `[57]` to jeden znak z listy |
| 3V, 3 V, 3.7V, 3,7 V | `'\b3(?:[.,]7)?\s*V\b'` | `(?:…)?` to opcjonalny kawałek, `\s*` to dowolne spacje |
| 12 V, ale nie 112 V ani 1.2 V | `'(?<![\d.,])12\s*V\b'` | `(?<![\d.,])` to „przed tym nie ma cyfry, kropki ani przecinka” |
| długość 30–45 mm | `'\b(?:3[0-9]\|4[0-5])\s*mm\b'` | |
| 1800–2400 K | `'\b(?:1800\|2000\|2200\|2400)\s*K\b'` | |

Znaki, które w wyrażeniach mają specjalne znaczenie: `. + * ? ( ) [ ] { } | \ ^ $`.
Żeby szukać ich dosłownie, poprzedź je `\`, np. `'DC\+'` albo `'1\.5W'`.

**Apostrofy.** Wzorce zapisuj w **pojedynczych apostrofach** `'...'`. TOML bierze wtedy tekst
dosłownie i `\b` czy `\d` działają bez podwajania ukośników. W cudzysłowach `"..."` trzeba by pisać
`\\b`. Jeśli sam wzorzec zawiera apostrof, użyj potrójnych: `'''don't'''`.

**Wspólne wzorce `[wzorce]`.** Długi wzorzec używany w kilku miejscach zdefiniuj raz:

```toml
[wzorce]
SIEC_230 = '(?<![\d.,])(?:AC\s*)?(?:110|220|230|240)\s*V\b'
```

i używaj go w regułach jako `@SIEC_230`. Możesz go też łączyć z innymi, np. `wzorzec = '@CIEPLA|warm'`.
Nazwa po `@` musi dokładnie odpowiadać nazwie w sekcji `[wzorce]`.

### Przykład: nowy profil od zera

Szukamy modułu ładowania Li-ion z USB-C. Ma być układ TP4056 lub IP2312, z zabezpieczeniem baterii,
a micro USB nas nie interesuje. Dopisz na końcu `profile.toml`:

```toml
[profile.ladowarka]
opis = "Moduł ładowania 1S Li-ion z USB-C i zabezpieczeniem"
frazy = [
    "TP4056 type-c module protection",
    "18650 charger board usb-c",
    "IP2312 charging module",
]
wymagane = ['TP4056|IP2312']
reguly = [
    { nazwa = "USB-C",          wzorzec = 'type[\s-]?c|usb[\s-]?c', tytul = 4, spec = 3, opis = 1 },
    { nazwa = "zabezpieczenie", wzorzec = 'protect|DW01|zabezpiecz', tytul = 3, spec = 3, opis = 1, cytuj = true },
    { nazwa = "prąd 1 A",       wzorzec = '\b1(?:[.,]0)?\s*A\b|1000\s*mA', tytul = 1, opis = 1 },
    { nazwa = "micro USB",      wzorzec = 'micro[\s-]?usb', tytul = -4, spec = -2, opis = 0 },
]
```

Następnie:

```bash
python scrapper.py --lista                                  # czy profil się wczytał
python scrapper.py --profil ladowarka --strony 1 --max 10   # próba
```

### Dopracowywanie reguł

1. **Uruchom małe wyszukiwanie** i obejrzyj raport.
2. **Szukaj złych ocen.** Zła aukcja wysoko? Zobacz w kolumnie „Fragmenty”, za co dostała punkty.
   Zwykle trzeba zawęzić wzorzec (dodać `\b`, `(?<![\d.,])`) albo dodać regułę z karą.
   Dobra aukcja nisko? Sprawdź, jak sprzedawca zapisuje dane (np. „DC3V”, „3 Volt”) i poszerz wzorzec.
3. **Popraw `profile.toml`** i przelicz raport **bez ponownego pobierania**:
   ```bash
   python scrapper.py --profil ladowarka --tylko-ocena
   ```
4. **Żeby zobaczyć też odrzucone aukcje**, dodaj `--min-ocena -50`.

Szybki test samego wzorca w Pythonie:

```bash
python -c "import re; print(re.findall(r'(?<![\d.,])12\s*V\b', 'zasilanie 12V, nie 112V ani 1.2 V', re.I))"
```

### Najczęstsze błędy

- **`Błąd w profile.toml: ...`**: zła składnia TOML. Najczęściej brakuje przecinka między regułami,
  przecinek jest między polami w `{ }`, albo nawias się nie domyka. Każda reguła `{ ... }` musi być
  w **jednej linii**.
- **`błędny wzorzec`**: niepoprawne wyrażenie regularne, np. niedomknięty nawias `(`.
  Komunikat podaje profil i opis błędu.
- **`nieznany wzorzec @NAZWA`**: literówka w nazwie albo brak jej w sekcji `[wzorce]`.
- **Reguła nigdy nie trafia:** sprawdź `\b` przy tekście z cyframi i jednostką. `'\b3V\b'` nie trafi
  w „DC3V”, bo między „C” a „3” nie ma granicy słowa. W takich miejscach używaj `(?<![\d.,])`.

---

## Pliki w katalogu

| Plik | Do repo? | Co to |
|---|---|---|
| `scrapper.py` | tak | skrypt |
| `profile.toml` | tak | profile wyszukiwania |
| `README.md` | tak | ten plik |
| `SKLEPY_TODO.md` | tak | jak działają strony sklepów i jak dodać kolejny (TME, Kamami, Botland, eBay) |
| `profil-przegladarki/` | **nigdy** | cookies i sesja logowania do sklepów, czyli dostęp do Twojego konta |
| `dane/` | **nigdy** | cache aukcji i kopie przeglądarki dla każdego profilu (kopie zawierają cookies) |
| `wyniki_*.html`, `wyniki_*.csv` | nie | raporty, do odtworzenia przez `--tylko-ocena` |

Wszystko, co „nie”, jest już w `.gitignore`.

## Rozwiązywanie problemów

- **`Brak Playwright`**: zainstaluj bibliotekę (zobacz [Instalacja](#instalacja)). Jeśli używasz venv,
  sprawdź, czy jest aktywne.
- **`Executable doesn't exist ... chromium`**: brakuje przeglądarki. Uruchom
  `python -m playwright install chromium`.
- **Skrypt stoi na captchy, choć ją rozwiązałeś**: naciśnij Enter w terminalu. Co 30 s skrypt
  wypisuje, po czym wciąż widzi captchę. Ta informacja przyda się przy zgłaszaniu błędu.
- **Przy każdej aukcji „brak danych z API”**: AliExpress prawdopodobnie zmienił swoją stronę.
  Skrypt działa dalej starą metodą (tekst strony), ale mniej dokładnie.
- **Zero linków w wynikach wyszukiwania**: sklep mógł zmienić adresy stron. Sprawdź w oknie
  przeglądarki, co się wyświetla. Może to też być captcha albo baner cookies, wtedy uruchom `--przegladarka`.

## Uwagi

Sklepy w regulaminach zwykle zabraniają automatycznego przeglądania. Skrypt jest pomyślany do
okazjonalnego, prywatnego szukania produktów. Robi długie przerwy, otwiera strony jak zwykły
użytkownik i nie omija zabezpieczeń (captchę rozwiązujesz sam). Nie ustawiaj dużego `--max`
ani małego `--tempo`.

---
---

<a id="english"></a>

# py-scrapper: AliExpress / Allegro listing finder (English)

[🇵🇱 Polska wersja powyżej](#py-scrapper-szukacz-aukcji-aliexpress--allegro)

The script searches AliExpress (or Allegro, a Polish marketplace) for the phrases you give it,
opens every listing it finds and **scores it** with your own rules, e.g. "+6 if the specification
says 3 V, −5 if it says 230 V". The output is an HTML/CSV report sorted best-first. Every listing in
the report shows the text snippets that earned its points, so you can verify a match without opening it.

What to search for is defined in [`profile.toml`](profile.toml). The bundled profiles look for
E14 LED bulbs running on 3–6 V, 3 V LED filaments and red 12 V E27 bulbs, but any other product can be described
the same way (see [Editing profile.toml](#editing-profiletoml)).

> **About the Polish names.** The command-line options, TOML keys and terminal messages are in Polish.
> The tables below translate every one of them. Search phrases and patterns can be in any language.

## How it works

1. **Collecting links.** The script opens a real Chromium window (via Playwright), runs each phrase
   from the profile through the shop's search and collects listing links from a few result pages.
2. **Title pre-scoring.** Each listing's title on the results page is scored with the rules' `tytul`
   points **before** the listing is opened. Listings below `--prog-listy` (default 0, e.g. "220V" in the
   title) are skipped, and the most promising ones are opened first. This saves time and captchas,
   because AliExpress search returns mostly 230 V bulbs anyway.
3. **Downloading listings.** It opens each listing.
   - **AliExpress:** the script captures the data the page already loads from AliExpress's own API
     (`mtop.aliexpress.pdp.pc.query`): title, item specifics (e.g. `Voltage: 3V`), variants, price
     and the seller's description. That data contains no ads or "recommended" products, so it is clean.
   - **Allegro:** title, price and description come from the product data embedded in the page
     (JSON-LD), and item parameters (e.g. "Rodzaj gwintu" = socket type, "Barwa światła" = light
     colour) from the "Parametry" section. Recommended and sponsored offers are not read.
   - If that data is missing, the script falls back to reading the whole page text, which is less accurate.
4. **Scoring.** Each rule in the profile checks the title, the specification and the description,
   and adds or subtracts points.
5. **Report.** Results from all shops go to one report, `wyniki_<profile>.html` and `.csv`
   ("wyniki" = results), with a "Sklep" (shop) column for easy price comparison.
   The report is rewritten after every listing, so you can keep it open in a browser and refresh it while the search runs.

Downloaded listings are cached in `dane/cache_<profile>_<shop>.json`, separately for each profile and
shop. Later runs skip them, and after changing your rules you can re-score everything offline with
`--tylko-ocena`. You can come back to a saved profile months later: `--lista` shows how many listings
each profile has and when it last ran.

## Installation

Requires **Python 3.11+** (for the built-in `tomllib`) and **Playwright** with Chromium. No other dependencies.

**Arch Linux:**

```bash
sudo pacman -S python-playwright
python -m playwright install chromium
```

**Any other OS (Debian/Ubuntu, Fedora, macOS, Windows), using a virtual environment:**

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install playwright
python -m playwright install chromium
```

Activate the environment before every run. On Debian/Ubuntu, if Chromium fails to start because of
missing system libraries, run `sudo python -m playwright install-deps chromium`.

Check that everything works (this command does not go online):

```bash
python scrapper.py --lista       # lists the profiles from profile.toml
```

## First run

**1. Prepare the browser profile (recommended):**

```bash
python scrapper.py --przegladarka
```

A browser window opens. Accept the cookies and, ideally, **log in to AliExpress**: logged-in users
get far fewer captchas. Then press Enter in the terminal. The session is stored in
`profil-przegladarki/` and reused on later runs. All shops of the profile are opened.

**2. Do a small test search:**

```bash
python scrapper.py --strony 1 --max 10
```

Leave the browser window alone (you can minimise it). After each listing the terminal prints a preview:

```
[3/10] https://www.aliexpress.com/item/1005010775885139.html
   · ocena +0  83,68zł  Żarówki LED C35 E14 3W, spiralne żarówki do kandelabrów, 220V…
     kształt C35 / świeczka w tytule (+2); filament / COG w tytule (+2); zasilanie 230 V w tytule (-5)
     [zasilanie 230 V · spec] Napięcie: 220-240 V
```

`ocena` = score. Markers: **★** strong match (≥ 8 points), **+** goes into the report,
**·** below the threshold, **✗** rejected (a required pattern is missing).

**3. Open the report** `wyniki_zarowka.html`. Green rows are strong matches, yellow rows are worth checking.

## Captchas

When a shop shows a "you are not a robot" check, the script detects it, plays a system sound,
shows a desktop notification (on Linux via `paplay`/`pw-play` and `notify-send`), prints a message
and **waits**. The sound repeats every 30 s for the first 3 minutes. `--cicho` (quiet) turns sound
and notifications off.

- **Solve the captcha in the browser window.** The script continues on its own once the check is gone.
- **Or type a command in the terminal:**
  - just **Enter**: "solved, carry on",
  - **`p`** + Enter: skip this listing,
  - **`k`** + Enter: stop and build the report from what has been downloaded so far.
- **Timeout:** after 10 minutes without a solution the listing is skipped automatically.
- **Ctrl+C:** stops at any time and still writes the report.

To get fewer captchas:

- **Log in** with `--przegladarka`.
- **Slow down:** `--tempo 2` doubles every pause, and `--przerwa-co 8` adds a long break
  (1–2.5 min) every 8 listings. Each captcha also slows the script down automatically.
- **Fetch fewer at once:** use a smaller `--max`. Thanks to the cache, the next run picks up where this one stopped.
- **Use a regular browser:** system Chromium instead of Playwright's build, e.g.
  `--chrome /usr/bin/chromium`. reCAPTCHA usually rates it better.

## Everyday use

```bash
python scrapper.py --lista                          # list profiles
python scrapper.py                                  # first profile, shops from its 'sklepy' field
python scrapper.py --profil filament --sklep allegro           # one shop only
python scrapper.py --profil zarowka --sklep aliexpress allegro # chosen shops
python scrapper.py --profil zarowka --sklep wszystkie          # all supported shops ("wszystkie" = all)
python scrapper.py --frazy "E14 3V candle" "C35 DC3V"   # custom phrases, rules from the profile
python scrapper.py --tylko-ocena                    # re-score from cache after editing rules (offline)
python scrapper.py --tylko-ocena --min-ocena -50    # show almost everything in the report
python scrapper.py --odswiez --max 60               # re-download old cache entries (see below)
```

**One-off search without editing the file.** Passing `--wymagane`, `--plus` or `--minus` builds a
temporary profile named `wlasny`. `--plus` patterns give +3 (title/spec) or +1 (description),
and `--minus` patterns give −5 or −2:

```bash
python scrapper.py --frazy "TP4056 type-c" "18650 charger module" \
    --wymagane "TP4056|IP2312" --plus "type-?c" "protect" --minus "micro ?usb"
```

**Several searches at once.** Each profile and shop has its own cache and its own browser copy in
`dane/`, so you can run several scripts in separate terminals:

```bash
python scrapper.py --profil zarowka                            # terminal 1
python scrapper.py --profil czerwona_e27_12v --sklep allegro   # terminal 2
```

The browser copy is created on a profile's first run from the main `profil-przegladarki/` (the one
`--przegladarka` opens), so your login carries over. The same profile and shop cannot run in two
terminals at once. Every window sends requests from the same IP address, so with several running
captchas may show up more often. `--tempo 2` helps.

**`--odswiez`** (refresh) applies to cache entries saved by an older version of the script, which read
the whole page text, ads included. Such AliExpress entries are left out of the report because they
can't be scored reliably. The script tells you at the end how many there are. `--odswiez` downloads them again through the API.

## All options

| Option | Meaning | Default | Description |
|---|---|---|---|
| `--profil NAME` | profile | first in file | profile from `profile.toml` |
| `--sklep S …` | shop(s) | from profile | `aliexpress`, `allegro` or `wszystkie` (all); without it, the profile's `sklepy` field (or `aliexpress`) |
| `--lista` | list | | list profiles and exit |
| `--frazy P1 P2 …` | phrases | from profile | custom search phrases |
| `--wymagane` / `--plus` / `--minus` | required / plus / minus | | one-off profile from the command line |
| `--strony N` | pages | 2 | result pages per phrase |
| `--max N` | | 40 | max listings to open in this run (per shop) |
| `--prog-listy N` | list threshold | 0 | only open listings whose title on the results page scores ≥ N; `-99` = open all |
| `--min-ocena N` | min score | 3 | listings scoring lower are left out of the report |
| `--tempo X` | pace | 1.0 | pause multiplier (2 = twice as slow) |
| `--przerwa-co N` | break every | 12 | long break every N listings; 0 = off |
| `--odswiez` | refresh | | re-download old AliExpress cache entries |
| `--tylko-ocena` | scoring only | | don't download anything, just rebuild the report from cache |
| `--przegladarka` | browser | | only open the browser window (log in, accept cookies) |
| `--chrome PATH` | | | use another browser binary, e.g. `/usr/bin/chromium` |
| `--cicho` | quiet | | no sound or notifications on captchas |
| `--headless` | | | no window; captchas cannot be solved, not recommended |

---

<a id="editing-profiletoml"></a>

## Editing profile.toml

[`profile.toml`](profile.toml) tells the script **what to search for** and **how to score** what it finds.
One profile = one product. You can have as many as you like and pick one with `--profil`.

### Key names: Polish → English

| TOML key | Meaning |
|---|---|
| `[wzorce]` | patterns: shared pattern snippets, used as `@NAME` |
| `[profile.NAME]` | a profile called NAME |
| `opis` (in a profile) | description of the profile |
| `frazy` | search phrases |
| `frazy_pl` | Polish search phrases (for Allegro) |
| `frazy_<shop>` | phrases for one shop only |
| `sklepy` | shops to search |
| `wymagane` | required patterns |
| `wymagane_tytul` | patterns required in the title on the results page |
| `reguly` | scoring rules |
| `nazwa` | rule name |
| `wzorzec` | pattern |
| `tytul` | points when found in the **title** |
| `spec` | points when found in the **specification / variants** |
| `opis` (in a rule) | points when found only in the **description** |
| `cytuj` | quote: show matching lines in the report |
| `chyba_ze` | "unless": exception pattern |

### File layout

```toml
[wzorce]                     # (optional) shared pattern snippets, used as @NAME
NISKIE_V = '...'

[profile.zarowka]            # profile called "zarowka"  →  --profil zarowka
opis = "..."
frazy = [ ... ]
wymagane = [ ... ]
reguly = [ ... ]

[profile.filament]           # another profile
...
```

The profile name is the part after `profile.`. Use plain ASCII letters, digits and `_`, e.g.
`[profile.usbc_charger]`. The first profile in the file is the default.

### Profile fields

| Field | Required | What it is |
|---|---|---|
| `opis` | no | short description, shown by `--lista` and in the report header |
| `frazy` | yes | phrases typed into the shop's search box, each searched separately |
| `frazy_pl` | no | Polish phrases for Polish shops (Allegro); AliExpress uses `frazy` |
| `frazy_<shop>` | no | phrases for one shop only, e.g. `frazy_allegro`; order: `frazy_<shop>` → `frazy_pl` → `frazy` |
| `sklepy` | no | which shops to search when `--sklep` isn't given, e.g. `["aliexpress", "allegro"]` |
| `wymagane` | no | patterns a listing **must** contain (every one of them), otherwise it is rejected immediately |
| `wymagane_tytul` | no | patterns the **title on the results page** must contain for the listing to be opened at all, e.g. the socket `'\bE[\s-]?27\b'`; saves time and captchas |
| `reguly` | yes | scoring rules, described below |

**Phrases** are plain text, as you would type them into the search box. On AliExpress, English phrases
work best (that is how sellers describe products). On Allegro, use Polish. Several different phrases
find more different listings. Each phrase × `--strony` is a separate set of result pages to go through.

**Required patterns** are a quick filter. For example `wymagane = ['\bE[\s-]?14\b']` drops anything
that never mentions an E14 socket. They are checked against the title, specification and description combined.

### Rules

Each rule is one line in curly braces:

```toml
reguly = [
    { nazwa = "voltage 3–4.2 V", wzorzec = '@NISKIE_V', tytul = 6, spec = 6, opis = 2, cytuj = true },
    { nazwa = "filament / COG",  wzorzec = 'filament|\bCOG\b', tytul = 2, opis = 1 },
]
```

| Field | Default | Meaning |
|---|---|---|
| `nazwa` | (required) | rule name shown in the report and terminal |
| `wzorzec` | (required) | what to look for: a plain word or a regular expression (case-insensitive) |
| `tytul` | 0 | points when the pattern is **in the title** |
| `spec` | = `tytul` | points when it is **in the item specifics or variants** (e.g. `Voltage: 3V`, a variant button "DC3V") |
| `opis` | 0 | points when it is **only in the seller's description** |
| `cytuj` | `false` | `true` = show the matching lines in the report for a quick visual check |
| `chyba_ze` | none | exception pattern: if it matches **in the same place** as `wzorzec`, the rule doesn't count |

**How scoring works:**

- **Exceptions (`chyba_ze`).** Multi-variant listings write e.g. "110V 220V 12V 24V" in one title.
  A 230 V penalty would then also throw out the 12 V variant. So the 230 V rule has
  `chyba_ze = '@NISKIE_V|@NISKIE_12'`: if a low voltage appears in the same place too, the penalty
  is not applied (the report says "pominięte, są też inne warianty", i.e. skipped, other variants exist).
- **Title pre-scoring:** on the results page the script only sees the title, so only the `tytul` points
  count. A strong `tytul` penalty (e.g. −8 for 230 V) filters such listings out before they are opened.
- **Only the most reliable match counts:** title first, then specification, then description.
  If "3V" appears both in the title and in the description, the rule gives only the `tytul` points, not both.
- **Negative points are penalties.** All rules apply together: a listing with "3V" in the description
  (+2) and "220V" in the specification (−5) ends up at −3.
- **The final score is the sum of all rules.** In the report, ≥ 8 is a green row and ≥ 4 is yellow.
  Tune the points so that an ideal listing reaches 8 or more, while a mere keyword match stays lower.
- **The seller's description is the least reliable source.** It often lists every possible variant
  and voltage at once, so give it fewer points than the title and the specification.
- **AliExpress category ranges** (e.g. "Napięcie: 0–5 V", "11-50 V") are picked by sellers from a list,
  often carelessly. Treat them as weak hints (few points, `spec` only) and don't use them in `chyba_ze`.

### Writing patterns

A pattern is a [Python regular expression](https://docs.python.org/3/library/re.html), but plain words
are enough to start with. Matching is case-insensitive.

| To find | Pattern | Notes |
|---|---|---|
| the word "filament" | `'filament'` | also matches "filaments" |
| one of several words | `'candle\|świecz\|kerze'` | `\|` means "or" |
| the whole word "COG" | `'\bCOG\b'` | `\b` = word boundary, so "COGNAC" won't match |
| E14, E-14, E 14 | `'\bE[\s-]?14\b'` | `[\s-]?` = optional space or hyphen |
| C35 or C37 | `'\bC3[57]\b'` | `[57]` = one character from the list |
| 3V, 3 V, 3.7V, 3,7 V | `'\b3(?:[.,]7)?\s*V\b'` | `(?:…)?` = optional part, `\s*` = any spaces |
| 12 V but not 112 V or 1.2 V | `'(?<![\d.,])12\s*V\b'` | `(?<![\d.,])` = "not preceded by a digit, dot or comma" |
| length 30–45 mm | `'\b(?:3[0-9]\|4[0-5])\s*mm\b'` | |
| 1800–2400 K | `'\b(?:1800\|2000\|2200\|2400)\s*K\b'` | |

Characters with a special meaning: `. + * ? ( ) [ ] { } | \ ^ $`. To match them literally, put `\`
in front, e.g. `'DC\+'` or `'1\.5W'`.

**Quotes.** Write patterns in **single quotes** `'...'`. TOML then takes the text literally, so `\b`
and `\d` work without doubling the backslash. In double quotes `"..."` you would need `\\b`.
If the pattern itself contains an apostrophe, use triple quotes: `'''don't'''`.

**Shared patterns `[wzorce]`.** Define a long pattern used in several places once:

```toml
[wzorce]
MAINS = '(?<![\d.,])(?:AC\s*)?(?:110|220|230|240)\s*V\b'
```

and use it in rules as `@MAINS`. It can be combined with other text, e.g. `wzorzec = '@CIEPLA|warm'`.
The name after `@` must exactly match a name in `[wzorce]`.

### Example: a new profile from scratch

We want a 1S Li-ion charging module with USB-C: a TP4056 or IP2312 chip with battery protection,
and no micro-USB. Append this to `profile.toml`:

```toml
[profile.charger]
opis = "1S Li-ion charging module with USB-C and protection"
frazy = [
    "TP4056 type-c module protection",
    "18650 charger board usb-c",
    "IP2312 charging module",
]
wymagane = ['TP4056|IP2312']
reguly = [
    { nazwa = "USB-C",      wzorzec = 'type[\s-]?c|usb[\s-]?c', tytul = 4, spec = 3, opis = 1 },
    { nazwa = "protection", wzorzec = 'protect|DW01|zabezpiecz', tytul = 3, spec = 3, opis = 1, cytuj = true },
    { nazwa = "1 A current", wzorzec = '\b1(?:[.,]0)?\s*A\b|1000\s*mA', tytul = 1, opis = 1 },
    { nazwa = "micro USB",  wzorzec = 'micro[\s-]?usb', tytul = -4, spec = -2, opis = 0 },
]
```

Then:

```bash
python scrapper.py --lista                                 # did the profile load?
python scrapper.py --profil charger --strony 1 --max 10    # test run
```

### Tuning the rules

1. **Run a small search** and look at the report.
2. **Look for wrong scores.** A bad listing ranked high? Check the snippets column to see what earned
   it points. Usually the pattern needs tightening (add `\b`, `(?<![\d.,])`) or you need a penalty rule.
   A good listing ranked low? Check how the seller writes it ("DC3V", "3 Volt", …) and widen the pattern.
3. **Edit `profile.toml`** and re-score **without downloading again**:
   ```bash
   python scrapper.py --profil charger --tylko-ocena
   ```
4. **To see rejected listings too**, add `--min-ocena -50`.

Quick pattern test in Python:

```bash
python -c "import re; print(re.findall(r'(?<![\d.,])12\s*V\b', 'power 12V, not 112V or 1.2 V', re.I))"
```

### Common mistakes

- **`Błąd w profile.toml: ...`** (error in profile.toml): TOML syntax. Usually a missing comma between
  rules, a comma placed between fields inside `{ }`, or an unclosed bracket. Each rule `{ ... }`
  must stay on **one line**.
- **`błędny wzorzec`** (invalid pattern): the regular expression is broken, e.g. an unclosed `(`.
  The message names the profile and the error.
- **`nieznany wzorzec @NAME`** (unknown pattern): a typo in the name, or it is missing from `[wzorce]`.
- **A rule never matches:** check `\b` next to digits and units. `'\b3V\b'` does not match "DC3V",
  because there is no word boundary between "C" and "3". Use `(?<![\d.,])` there instead.

---

## Files

| File | In the repo? | What it is |
|---|---|---|
| `scrapper.py` | yes | the script |
| `profile.toml` | yes | search profiles |
| `README.md` | yes | this file |
| `SKLEPY_TODO.md` | yes | how the shops' pages work and how to add another (TME, Kamami, Botland, eBay); in Polish |
| `profil-przegladarki/` | **never** | browser cookies and shop login session, i.e. access to your account |
| `dane/` | **never** | per-profile listing cache and browser copies (the copies contain cookies) |
| `wyniki_*.html`, `wyniki_*.csv` | no | reports, rebuildable with `--tylko-ocena` |

Everything marked "no" is already in `.gitignore`.

## Troubleshooting

- **`Brak Playwright`** (Playwright missing): install it (see [Installation](#installation)).
  If you use a venv, make sure it is active.
- **`Executable doesn't exist ... chromium`**: the browser is missing. Run `python -m playwright install chromium`.
- **Stuck on a captcha you already solved**: press Enter in the terminal. Every 30 s the script prints
  what still looks like a captcha to it (`nadal widzę captchę`). Include that line when reporting a bug.
- **"brak danych z API" (no API data) on every listing**: AliExpress has probably changed its page.
  The script carries on with the old page-text method, but less accurately.
- **Zero links found in search results**: the shop may have changed its URLs. Check what the browser
  window shows. It may also be a captcha or a cookie banner, in which case run `--przegladarka`.

## Note

Shops' terms of service usually forbid automated browsing. This script is meant for occasional,
personal product searches. It pauses a lot, loads pages like a normal user and does not bypass any
protection (you solve captchas yourself). Don't set a large `--max` or a low `--tempo`.
