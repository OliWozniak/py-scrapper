# Szukacz aukcji AliExpress / Allegro

Skrypt przeszukuje AliExpress (lub Allegro) według podanych fraz, otwiera każdą znalezioną aukcję
i **ocenia ją punktowo** według Twoich reguł, np. „+6 za napięcie 3 V w specyfikacji, −5 za 230 V”.
Wynik to raport HTML/CSV posortowany od najlepszych trafień. Przy każdej aukcji są fragmenty tekstu,
za które dostała punkty, więc szybko sprawdzisz trafienie bez otwierania aukcji.

Czego szukać, definiujesz w pliku [`profile.toml`](profile.toml). Wbudowane przykłady szukają
żarówek E14 na 3–4,2 V i filamentów LED 3 V, ale w ten sam sposób opiszesz dowolny inny produkt
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
2. **Pobieranie aukcji.** Otwiera kolejne aukcje.
   - **AliExpress:** przechwytuje dane, które strona i tak pobiera ze swojego API: tytuł,
     specyfikację (np. `Voltage: 3V`), warianty, cenę i opis sprzedawcy. Nie ma w nich reklam ani
     poleconych produktów, więc dane są czyste.
   - **Allegro** (oraz AliExpress, gdy API nie odpowie): skrypt czyta tekst całej strony, co jest mniej dokładne.
3. **Ocena.** Każda reguła z profilu sprawdza tytuł, specyfikację i opis, po czym przyznaje lub
   odejmuje punkty.
4. **Raport.** Wyniki trafiają do `wyniki_<profil>_<sklep>.html` i `.csv`. Raport odświeża się po
   każdej aukcji, więc możesz go mieć otwartego w przeglądarce i odświeżać w trakcie.

Pobrane aukcje zapisują się w `cache_aukcji.json`. Kolejne uruchomienia nie pobierają ich drugi raz,
a po zmianie reguł możesz przeliczyć oceny bez internetu (`--tylko-ocena`).

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
python szukaj_zarowek.py --lista
```

Powinna się pojawić lista profili z `profile.toml`.

## Pierwsze uruchomienie

**1. Przygotuj profil przeglądarki (zalecane).** Otwórz okno przeglądarki, którego będzie używał skrypt:

```bash
python szukaj_zarowek.py --przegladarka
```

W oknie zaakceptuj cookies i najlepiej **zaloguj się na AliExpress**. Zalogowany użytkownik
dostaje dużo mniej captchy. Gotowe? Wróć do terminala i naciśnij Enter. Sesja zapisuje się w katalogu
`profil-przegladarki/` i zostaje na kolejne uruchomienia. Dla Allegro dodaj `--sklep allegro`.

**2. Zrób małe próbne wyszukiwanie:**

```bash
python szukaj_zarowek.py --strony 1 --max 10
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

**3. Otwórz raport** `wyniki_zarowka_aliexpress.html` w przeglądarce. Zielone wiersze to mocne trafienia,
żółte są do sprawdzenia.

Działa? Uruchom pełne wyszukiwanie: `python szukaj_zarowek.py`.

## Captcha

Sklepy nie lubią automatycznego przeglądania i co jakiś czas pokazują weryfikację „nie jestem robotem”.
Skrypt sam ją wykrywa: wydaje dźwięk, wypisuje komunikat i **czeka**.

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
python szukaj_zarowek.py --lista                          # jakie są profile
python szukaj_zarowek.py                                  # pierwszy profil z profile.toml, AliExpress
python szukaj_zarowek.py --profil filament                # inny profil
python szukaj_zarowek.py --profil filament --sklep allegro
python szukaj_zarowek.py --frazy "E14 3V candle" "C35 DC3V"   # własne frazy, reguły z profilu
python szukaj_zarowek.py --tylko-ocena                    # przelicz raport po zmianie reguł (bez internetu)
python szukaj_zarowek.py --tylko-ocena --min-ocena -50    # pokaż w raporcie prawie wszystko
python szukaj_zarowek.py --odswiez --max 60               # pobierz ponownie stare wpisy (patrz niżej)
```

**Jednorazowe wyszukiwanie bez edycji pliku.** Gdy podasz `--wymagane`, `--plus` lub `--minus`, skrypt
tworzy tymczasowy profil `wlasny`. Za wzorce z `--plus` daje +3 (tytuł/specyfikacja) albo +1 (opis),
a za wzorce z `--minus` −5 albo −2:

```bash
python szukaj_zarowek.py --frazy "TP4056 type-c" "18650 charger module" \
    --wymagane "TP4056|IP2312" --plus "type-?c" "protect" --minus "micro ?usb"
```

**`--odswiez`** dotyczy wpisów z cache pobranych starszą wersją skryptu (z tekstu całej strony,
razem z reklamami innych produktów). Takie wpisy z AliExpress są oceniane tylko po tytule
i mają w raporcie dopisek „stary wpis”. `--odswiez` pobiera je ponownie, już przez API.

## Wszystkie opcje

| Opcja | Domyślnie | Opis |
|---|---|---|
| `--profil NAZWA` | pierwszy w pliku | profil z `profile.toml` |
| `--sklep` | `aliexpress` | `aliexpress` albo `allegro` |
| `--lista` | | pokaż profile i zakończ |
| `--frazy F1 F2 …` | z profilu | własne frazy wyszukiwania |
| `--wymagane`, `--plus`, `--minus` | | jednorazowy profil z linii poleceń |
| `--strony N` | 2 | ile stron wyników na każdą frazę |
| `--max N` | 40 | ile najwyżej aukcji otworzyć w tym uruchomieniu |
| `--min-ocena N` | 3 | aukcje z niższą oceną nie trafiają do raportu |
| `--tempo X` | 1.0 | mnożnik przerw (2 = dwa razy wolniej) |
| `--przerwa-co N` | 12 | co ile aukcji dłuższa przerwa; 0 = wyłącz |
| `--odswiez` | | pobierz ponownie stare wpisy AliExpress z cache |
| `--tylko-ocena` | | nic nie pobieraj, tylko przelicz raport z cache |
| `--przegladarka` | | tylko otwórz okno (logowanie, cookies) |
| `--chrome ŚCIEŻKA` | | użyj innej przeglądarki, np. `/usr/bin/chromium` |
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
| `wymagane` | nie | lista wzorców, które aukcja **musi** zawierać (każdy z nich), inaczej od razu odpada |
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

**Jak liczone są punkty:**

- **Liczy się tylko najpewniejsze miejsce trafienia:** tytuł, potem specyfikacja, potem opis.
  Jeśli „3V” jest i w tytule, i w opisie, reguła daje tylko punkty `tytul`, a nie sumę.
- **Ujemne punkty to kara.** Do oceny aukcji wchodzą wszystkie reguły naraz: aukcja z „3V”
  w opisie (+2) i „220V” w specyfikacji (−5) dostaje razem −3.
- **Ocenę końcową sumuje się ze wszystkich reguł.** W raporcie ≥ 8 pkt to zielony wiersz, a ≥ 4 żółty.
  Dobierz punkty tak, żeby idealna aukcja miała 8 lub więcej, a zwykłe trafienie „po słowach” mniej.
- **Opis sprzedawcy jest najmniej wiarygodny**, bo często wymienia wszystkie możliwe warianty
  i napięcia naraz. Dawaj mu mniej punktów niż tytułowi i specyfikacji.
- **Stare wpisy z AliExpress** (sprzed wersji z API) mają pustą specyfikację i opis, więc liczą się
  tylko punkty `tytul`.

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
python szukaj_zarowek.py --lista                                  # czy profil się wczytał
python szukaj_zarowek.py --profil ladowarka --strony 1 --max 10   # próba
```

### Dopracowywanie reguł

1. **Uruchom małe wyszukiwanie** i obejrzyj raport.
2. **Szukaj złych ocen.** Zła aukcja wysoko? Zobacz w kolumnie „Fragmenty”, za co dostała punkty.
   Zwykle trzeba zawęzić wzorzec (dodać `\b`, `(?<![\d.,])`) albo dodać regułę z karą.
   Dobra aukcja nisko? Sprawdź, jak sprzedawca zapisuje dane (np. „DC3V”, „3 Volt”) i poszerz wzorzec.
3. **Popraw `profile.toml`** i przelicz raport **bez ponownego pobierania**:
   ```bash
   python szukaj_zarowek.py --profil ladowarka --tylko-ocena
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
| `szukaj_zarowek.py` | tak | skrypt |
| `profile.toml` | tak | profile wyszukiwania |
| `README.md` | tak | ten plik |
| `profil-przegladarki/` | **nigdy** | cookies i sesja logowania do sklepów, czyli dostęp do Twojego konta |
| `cache_aukcji.json` | nie | pobrane aukcje (duże, zmieniają się co uruchomienie) |
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
