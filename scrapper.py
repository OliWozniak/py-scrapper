#!/usr/bin/env python3
"""
Szukacz produktów na AliExpress i Allegro, z oceną aukcji według reguł.

Jak działa:
  1. Otwiera prawdziwą przeglądarkę (Playwright + Chromium), wchodzi w wyniki
     wyszukiwania dla podanych fraz i zbiera linki do aukcji.
  2. Otwiera każdą aukcję, przewija ją (żeby doczytał się opis) i pobiera tekst.
  3. Ocenia aukcje według reguł z profilu (plik profile.toml) i zapisuje
     raport wyniki_<profil>_<sklep>.html / .csv, od najlepszych.

Czego szukać – definiujesz w profile.toml (jeden blok = jeden produkt).
Szybkie jednorazowe wyszukiwanie bez edycji pliku:
    python scrapper.py --frazy "TP4056 type-c" --wymagane TP4056 --plus "type-?c" --minus "micro ?usb"

Przykłady:
    python scrapper.py --lista                 # pokaż dostępne profile
    python scrapper.py                         # profil zarowka, AliExpress
    python scrapper.py --profil filament --sklep allegro
    python scrapper.py --tylko-ocena           # przelicz z cache, bez internetu
    python scrapper.py --przegladarka          # otwórz okno, żeby się zalogować

Captcha: gdy sklep pokaże weryfikację, skrypt to wykryje, zapiszczy i CZEKA,
aż ją rozwiążesz w oknie przeglądarki – potem sam rusza dalej (nie trzeba
naciskać Enter). Strona, na której była captcha, jest pobierana ponownie.
"""

import argparse
import csv
import html
import json
import random
import re
import select
import sys
import time
import tomllib
from pathlib import Path
from urllib.parse import quote, quote_plus

KATALOG = Path(__file__).resolve().parent
PLIK_PROFILI = KATALOG / "profile.toml"
# Główny profil przeglądarki (logowanie, cookies) – wzorzec kopiowany dla każdego
# profilu wyszukiwania, żeby kilka skryptów mogło działać naraz.
PROFIL_PRZEGLADARKI = KATALOG / "profil-przegladarki"
# Dane każdego profilu wyszukiwania (cache aukcji, kopia przeglądarki) – osobno,
# żeby równoległe uruchomienia sobie nie przeszkadzały.
DANE = KATALOG / "dane"
# Tego nie kopiujemy z głównego profilu przeglądarki (duże cache, blokady)
POMIN_PRZY_KOPII = ("Cache", "Code Cache", "GPUCache", "GrShaderCache", "GraphiteDawnCache",
                    "ShaderCache", "DawnCache", "component_crx_cache", "extensions_crx_cache",
                    "BrowserMetrics*", "Singleton*", "*.lock", "lockfile")


def plik_cache(nazwa, sklep):
    return DANE / f"cache_{nazwa}_{sklep}.json"


def katalog_przegladarki(nazwa, sklep):
    """Osobny katalog przeglądarki dla pary profil+sklep. Przy pierwszym użyciu
    kopiowany z głównego profilu, więc zalogowanie i cookies przechodzą."""
    kat = DANE / f"przegladarka_{nazwa}_{sklep}"
    if not kat.exists() and PROFIL_PRZEGLADARKI.exists():
        import shutil
        print(f"Kopiuję zalogowany profil przeglądarki do {kat.relative_to(KATALOG)}/ …")
        shutil.copytree(PROFIL_PRZEGLADARKI, kat, ignore=shutil.ignore_patterns(*POMIN_PRZY_KOPII),
                        symlinks=True, ignore_dangling_symlinks=True)
    return kat

# Tekst poniżej tych nagłówków to zwykle polecane INNE produkty – ucinamy go,
# żeby nie dawały fałszywych trafień.
ZNACZNIKI_KONCA = [
    "More to love", "Więcej do pokochania", "Recommended for you", "Polecane dla Ciebie",
    "Customers also viewed", "Klienci oglądali również", "Inne oferty", "Podobne oferty",
    "Sprawdź także", "Zobacz także",
]

SKLEPY = {
    "aliexpress": {
        "url_wyszukiwania": lambda fraza, s: (
            f"https://www.aliexpress.com/w/wholesale-{quote_plus(fraza).replace('+', '-')}.html?page={s}"
        ),
        "link": re.compile(r"/item/(\d+)\.html"),
        "normalizuj": lambda m: f"https://www.aliexpress.com/item/{m.group(1)}.html",
    },
    "allegro": {
        "url_wyszukiwania": lambda fraza, s: (
            f"https://allegro.pl/listing?string={quote_plus(fraza)}&p={s}"
        ),
        # linki do ofert mają kilka postaci: /produkt/…?offerId=123, /oferta/nazwa-123
        # albo (sponsorowane) przekierowanie z zakodowanym %2Foferta%2F123
        "link": re.compile(r"allegro\.pl.*?(?:[?&]offerId=|/oferta/(?:[\w-]*-)?|%2Foferta%2F(?:[\w-]*-)?)(\d{8,})"),
        "normalizuj": lambda m: f"https://allegro.pl/oferta/{m.group(1)}",
        "start": "https://allegro.pl",
        # parametry oferty: blok tekstu między nagłówkami (pary linii klucz/wartość)
        "parametry": (r"\nParametry\n", r"\n(?:WSZYSTKIE PARAMETRY|Opis)\n"),
    },
}
SKLEPY["aliexpress"]["start"] = "https://www.aliexpress.com"
# język fraz: profil może mieć frazy_pl / frazy_en wspólne dla sklepów w danym języku
for _s in SKLEPY:
    SKLEPY[_s]["jezyk"] = "en" if _s == "aliexpress" else "pl"


def sklep_z_url(url):
    # Kolejne sklepy: patrz SKLEPY_TODO.md
    for nazwa, host in (("aliexpress", "aliexpress."), ("allegro", "allegro.pl")):
        if host in url:
            return nazwa
    return "?"

# Po czym poznać stronę weryfikacji. AliExpress przekierowuje na
# .../_____tmd_____/punish i wstawia reCAPTCHA w ramce, Allegro używa DataDome.
# (Nie sprawdzamy samego "recaptcha" w adresach ramek – niewidoczna reCAPTCHA
# bywa też na zwykłych stronach i skrypt czekałby w nieskończoność.)
CAPTCHA_W_URL = ("_____tmd_____", "/punish", "captcha-delivery.com")
CAPTCHA_W_TEKSCIE = ("we need to check if you are a robot", "nie jestem robotem",
                     "slide to verify", "przesuń suwak", "verify you are human",
                     "unusual traffic", "potwierdź, że nie jesteś robotem",
                     "jesteś robotem", "access is temporarily restricted",
                     # Cloudflare (np. TME) – zwykle przechodzi samo po kilku sekundach
                     "verifying you are human", "sprawdzanie, czy jesteś człowiekiem",
                     "weryfikacja, czy jesteś człowiekiem", "potwierdź, że jesteś człowiekiem")


# --------------------------------------------------------------------------
# PROFILE
# --------------------------------------------------------------------------

def wczytaj_profile():
    if not PLIK_PROFILI.exists():
        sys.exit(f"Brak pliku {PLIK_PROFILI}")
    with open(PLIK_PROFILI, "rb") as f:
        try:
            dane = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            sys.exit(f"Błąd w {PLIK_PROFILI.name}: {e}")
    wzorce = dane.get("wzorce", {})

    def rozwin(rx):
        # @NAZWA -> (?:wzorzec) z sekcji [wzorce]
        def zamien(m):
            if m.group(1) not in wzorce:
                sys.exit(f"{PLIK_PROFILI.name}: nieznany wzorzec @{m.group(1)}")
            return f"(?:{wzorce[m.group(1)]})"
        return re.sub(r"@([A-Za-z_][A-Za-z0-9_]*)", zamien, rx)

    profile = {}
    for nazwa, p in dane.get("profile", {}).items():
        try:
            reguly = [
                {"nazwa": r["nazwa"], "rx": re.compile(rozwin(r["wzorzec"]), re.I),
                 "tytul": int(r.get("tytul", 0)), "opis": int(r.get("opis", 0)),
                 "spec": int(r.get("spec", r.get("tytul", 0))),
                 "cytuj": bool(r.get("cytuj", False)),
                 "chyba_ze": re.compile(rozwin(r["chyba_ze"]), re.I) if r.get("chyba_ze") else None}
                for r in p.get("reguly", [])
            ]
            wymagane = [re.compile(rozwin(w), re.I) for w in p.get("wymagane", [])]
            wymagane_tytul = [re.compile(rozwin(w), re.I) for w in p.get("wymagane_tytul", [])]
        except re.error as e:
            sys.exit(f"{PLIK_PROFILI.name}, profil '{nazwa}': błędny wzorzec – {e}")
        except KeyError as e:
            sys.exit(f"{PLIK_PROFILI.name}, profil '{nazwa}': reguła bez pola {e}")
        profile[nazwa] = {"opis": p.get("opis", ""), "frazy": p.get("frazy", []),
                          # frazy dla sklepu: frazy_<sklep> → frazy_<język sklepu> → frazy
                          "frazy_sklep": {s: p.get(f"frazy_{s}") or p.get(f"frazy_{SKLEPY[s]['jezyk']}")
                                          for s in SKLEPY if p.get(f"frazy_{s}") or p.get(f"frazy_{SKLEPY[s]['jezyk']}")},
                          "wymagane": wymagane, "wymagane_tytul": wymagane_tytul, "reguly": reguly,
                          "sklepy": p.get("sklepy", [])}
        nieznane = [s for s in profile[nazwa]["sklepy"] if s not in SKLEPY]
        if nieznane:
            sys.exit(f"{PLIK_PROFILI.name}, profil '{nazwa}': nieznany sklep {nieznane}. "
                     f"Dostępne: {', '.join(SKLEPY)}")
    if not profile:
        sys.exit(f"{PLIK_PROFILI.name} nie zawiera żadnego [profile.xxx]")
    return profile


def profil_z_cli(a):
    """Jednorazowy profil z --wymagane/--plus/--minus."""
    def rx(w):
        try:
            return re.compile(w, re.I)
        except re.error:
            return re.compile(re.escape(w), re.I)
    reguly = [{"nazwa": f"+ {w}", "rx": rx(w), "tytul": 3, "spec": 3, "opis": 1, "cytuj": True,
               "chyba_ze": None} for w in a.plus or []]
    reguly += [{"nazwa": f"− {w}", "rx": rx(w), "tytul": -5, "spec": -5, "opis": -2, "cytuj": True,
                "chyba_ze": None} for w in a.minus or []]
    return {"opis": "profil z linii poleceń", "frazy": a.frazy or [], "frazy_sklep": {}, "wymagane_tytul": [],
            "sklepy": [],
            "wymagane": [rx(w) for w in a.wymagane or []], "reguly": reguly}


# --------------------------------------------------------------------------
# OCENA
# --------------------------------------------------------------------------

def fragment(tekst, m, szer=70):
    a, b = max(0, m.start() - szer), min(len(tekst), m.end() + szer)
    return ("…" if a else "") + " ".join(tekst[a:b].split()) + ("…" if b < len(tekst) else "")


def sekcje(dane, sklep_url=""):
    """(specyfikacja+warianty, opis). Dla starych wpisów z AliExpress (tekst całej
    strony z reklamami innych produktów) tekst jest pomijany – liczy się sam tytuł."""
    tekst = dane.get("tekst", "")
    if dane.get("zrodlo") in ("api", "ldjson"):
        spec, _, opis = tekst.partition("\n\nOPIS\n")
        return spec, opis
    if "/item/" in sklep_url:
        return "", ""
    return "", tekst


def linia(tekst, m, maks=180):
    """Cała linia z trafieniem (czytelniej niż wycinek), a dla długich linii wycinek."""
    a = tekst.rfind("\n", 0, m.start()) + 1
    b = tekst.find("\n", m.end())
    b = len(tekst) if b < 0 else b
    return " ".join(tekst[a:b].split()) if b - a <= maks else fragment(tekst, m)


def ocen(dane, profil, url=""):
    tytul = dane.get("tytul", "")
    spec, opis = sekcje(dane, url)
    calosc = f"{tytul}\n{spec}\n{opis}"
    for wym in profil["wymagane"]:
        if not wym.search(calosc):
            return -99, ["brak wymaganego: " + wym.pattern], []
    wynik, powody, cytaty = 0, [], []
    for r in profil["reguly"]:
        # liczy się najpewniejsze miejsce: tytuł > specyfikacja/warianty > opis
        for gdzie, tekst, pkt in (("tytule", tytul, r["tytul"]), ("specyfikacji", spec, r["spec"]),
                                  ("opisie", opis, r["opis"])):
            if tekst and r["rx"].search(tekst):
                if r["chyba_ze"] and r["chyba_ze"].search(tekst):
                    # np. "220V | 12V" – aukcja z kilkoma wariantami, nie karzemy
                    if pkt:
                        powody.append(f"{r['nazwa']} w {gdzie} – pominięte, są też inne warianty")
                elif pkt:
                    wynik += pkt
                    powody.append(f"{r['nazwa']} w {gdzie} ({pkt:+d})")
                break
        if r["cytuj"]:
            for etykieta, tekst in (("spec", spec), ("opis", opis)):
                for m in list(r["rx"].finditer(tekst))[:2]:
                    cytaty.append(f"[{r['nazwa']} · {etykieta}] {linia(tekst, m)}")
    return wynik, powody, cytaty


def ocen_tytul(tytul, profil):
    """Wstępna ocena samego tytułu z listy wyników – decyduje, czy warto otwierać aukcję."""
    if not tytul.strip():  # nie udało się odczytać tytułu z listy – otwieramy na wszelki wypadek
        return 0, ["brak tytułu na liście"]
    for w in profil["wymagane_tytul"]:
        if not w.search(tytul):
            return -99, [f"brak w tytule: {w.pattern}"]
    wynik, powody = 0, []
    for r in profil["reguly"]:
        if r["tytul"] and r["rx"].search(tytul) and not (r["chyba_ze"] and r["chyba_ze"].search(tytul)):
            wynik += r["tytul"]
            powody.append(f"{r['nazwa']} ({r['tytul']:+d})")
    return wynik, powody


def stary_wpis(url, d):
    """Wpis AliExpress sprzed wersji z API – tekst całej strony z reklamami, bezużyteczny do oceny."""
    return "/item/" in url and d.get("zrodlo") != "api"


def utnij_polecane(tekst):
    poz = [tekst.find(z) for z in ZNACZNIKI_KONCA if tekst.find(z) > 500]
    return tekst[: min(poz)] if poz else tekst


def cena(tekst):
    m = re.search(r"(\d{1,4}[.,]\d{2})\s*(zł|PLN)|(?:US\s*)?\$\s*(\d{1,4}[.,]\d{2})|€\s*(\d{1,4}[.,]\d{2})", tekst)
    return m.group(0) if m else ""


def wyglada_na_captche(dane):
    """Wpis w cache, który tak naprawdę jest stroną weryfikacji."""
    t = (dane.get("tytul", "") + " " + dane.get("tekst", "")[:3000]).lower()
    return len(dane.get("tekst", "")) < 1500 and any(s in t for s in CAPTCHA_W_TEKSCIE + ("recaptcha",))


# --------------------------------------------------------------------------
# PRZEGLĄDARKA
# --------------------------------------------------------------------------

class Tempo:
    """Pilnuje przerw. Po każdej captchy zwalnia, żeby kolejna nie przyszła szybko."""

    def __init__(self, mnoznik):
        self.mnoznik = mnoznik
        self.licznik = 0

    def pauza(self, a, b):
        time.sleep(random.uniform(a, b) * self.mnoznik)

    def po_aukcji(self, co_ile):
        self.licznik += 1
        if co_ile and self.licznik % co_ile == 0:
            s = random.uniform(60, 150) * self.mnoznik
            print(f"   … dłuższa przerwa {s:.0f} s (co {co_ile} aukcji)")
            time.sleep(s)
        else:
            self.pauza(5, 12)

    def zwolnij(self):
        self.mnoznik = min(self.mnoznik * 1.5, 5)
        print(f"   (zwalniam: tempo ×{self.mnoznik:.1f})")


class KoniecSzukania(Exception):
    """Użytkownik wpisał 'k' podczas captchy – kończymy i robimy raport."""


def widoczna(f, page):
    if f == page.main_frame:
        return True
    try:
        el = f.frame_element()
        b = el.bounding_box()
        return bool(b and b["width"] > 50 and b["height"] > 50) and el.is_visible()
    except Exception:
        return False


def powod_captchy(page):
    """Po czym wykryto captchę; None = brak, '?' = nie da się teraz sprawdzić."""
    try:
        if any(s in page.url.lower() for s in CAPTCHA_W_URL):
            return "adres strony z weryfikacją"
        for f in page.frames:
            # niewidoczne ramki pomijamy – AliExpress potrafi zostawić ukrytą
            # ramkę po rozwiązanej captchy i wtedy czekalibyśmy w nieskończoność
            if not widoczna(f, page):
                continue
            hit = next((s for s in CAPTCHA_W_URL if s in f.url.lower()), None)
            if hit:
                return f"ramka {hit}"
            try:
                t = f.inner_text("body", timeout=1500)[:3000].lower()
            except Exception:
                continue
            hit = next((s for s in CAPTCHA_W_TEKSCIE if s in t), None)
            if hit:
                return f"tekst „{hit}”"
    except Exception:
        return "?"  # strona akurat się przeładowuje
    return None


_STDIN_ZAMKNIETE = False


def wpisano():
    """Linia wpisana w terminalu (bez blokowania), albo None."""
    global _STDIN_ZAMKNIETE
    if _STDIN_ZAMKNIETE:
        return None
    try:
        gotowe, _, _ = select.select([sys.stdin], [], [], 0)
        if not gotowe:
            return None
        linia = sys.stdin.readline()
        if linia == "":  # brak terminala (uruchomienie w tle) – nie traktuj jak Enter
            _STDIN_ZAMKNIETE = True
            return None
        return linia.strip().lower()
    except Exception:
        return None


CICHO = False
DZWIEKI = ("/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga",
           "/usr/share/sounds/freedesktop/stereo/bell.oga")


def alarm(tytul, tresc):
    """Zwraca uwagę użytkownika: dźwięk systemowy + powiadomienie na pulpicie.
    Sam dzwonek terminala (\\a) bywa wyciszony, np. w terminalu VS Code."""
    if CICHO:
        return
    import shutil
    import subprocess
    print("\a", end="", flush=True)
    try:
        if shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-u", "critical", "-a", "scrapper", tytul, tresc],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        dzwiek = next((d for d in DZWIEKI if Path(d).exists()), None)
        odtwarzacz = next((o for o in ("paplay", "pw-play", "aplay") if shutil.which(o)), None)
        if dzwiek and odtwarzacz:
            subprocess.Popen([odtwarzacz, dzwiek], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif shutil.which("canberra-gtk-play"):
            subprocess.Popen(["canberra-gtk-play", "-i", "bell"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def czekaj_na_captche(page, headless, tempo, limit_min=10):
    """'brak' – nie było captchy, 'rozwiazana' – była (stronę trzeba załadować
    ponownie), 'pomin' – nie udało się, pomiń tę stronę."""
    powod = powod_captchy(page)
    if powod in (None, "?"):
        return "brak"
    # część weryfikacji (Cloudflare) przechodzi sama – chwilę czekamy bez alarmu
    for _ in range(5):
        time.sleep(2)
        if powod_captchy(page) is None:
            return "rozwiazana"
    if headless:
        sys.exit("\nSklep pokazał captchę, a w trybie --headless nie da się jej rozwiązać. "
                 "Uruchom bez --headless.")
    alarm("Captcha – potrzebna pomoc", "Rozwiąż weryfikację w oknie przeglądarki, skrypt czeka.")
    print(f"\n>>> CAPTCHA ({powod}). Rozwiąż ją w oknie przeglądarki – skrypt sam ruszy, gdy zniknie.\n"
          f"    Możesz też wpisać w terminalu:  Enter = jedź dalej · p + Enter = pomiń tę stronę"
          f" · k + Enter = zakończ i zrób raport")
    start = ostatni_komunikat = time.time()
    czyste = 0
    while czyste < 2:  # 2 kolejne sprawdzenia bez captchy = naprawdę przeszło
        time.sleep(2)
        cmd = wpisano()
        if cmd is not None:
            if cmd.startswith("k"):
                raise KoniecSzukania
            if cmd.startswith("p"):
                print(">>> Pomijam tę stronę.")
                tempo.zwolnij()
                return "pomin"
            break
        powod = powod_captchy(page)
        czyste = czyste + 1 if powod is None else 0
        if powod and powod != "?" and time.time() - ostatni_komunikat > 30:
            print(f"    … nadal widzę captchę ({powod})")
            if time.time() - start < 180:  # przypomnij dźwiękiem przez pierwsze 3 minuty
                alarm("Captcha nadal czeka", "Rozwiąż weryfikację w oknie przeglądarki.")
            ostatni_komunikat = time.time()
        if time.time() - start > limit_min * 60:
            print(f">>> {limit_min} min bez rozwiązania – pomijam tę stronę.")
            tempo.zwolnij()
            return "pomin"
    print(">>> OK, jadę dalej.")
    tempo.zwolnij()
    tempo.pauza(8, 15)
    return "rozwiazana"


def otworz(page, url, headless, tempo, prob=3):
    """Otwiera stronę; jeśli była captcha, po jej rozwiązaniu ładuje stronę od nowa."""
    for _ in range(prob):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"   błąd ładowania: {str(e).splitlines()[0]}")
            tempo.pauza(5, 10)
            continue
        tempo.pauza(1.5, 3)
        stan = czekaj_na_captche(page, headless, tempo)
        if stan == "brak":
            return True
        if stan == "pomin":
            return False
    print("   nie udało się otworzyć strony bez captchy – pomijam")
    return False


def przewin(page, krokow=12):
    for _ in range(krokow):
        try:
            page.mouse.wheel(0, random.randint(500, 1100))
        except Exception as e:
            if "closed" in str(e):
                raise
            return
        time.sleep(random.uniform(0.3, 0.9))


def zbierz_linki(page, sklep, fraza, strony, headless, tempo):
    cfg = SKLEPY[sklep]
    linki = {}  # url -> tekst karty z listy wyników (tytuł, cena…)
    for s in range(1, strony + 1):
        url = cfg["url_wyszukiwania"](fraza, s)
        print(f"  wyniki: {url}")
        if not otworz(page, url, headless, tempo):
            break
        przewin(page, 8)
        # tekst kafelka/wiersza produktu (tytuł, czasem parametry) – do wstępnej oceny
        karty = page.eval_on_selector_all("a[href]", """els => els.map(e => {
            const c = e.closest('tr, article');
            const t = (c && c.innerText.length < 700) ? c.innerText : (e.innerText || e.title || '');
            return [e.href, t.slice(0, 400)];
        })""")
        nowe = 0
        for h, tekst in karty:
            m = cfg["link"].search(h)
            if m:
                u = cfg["normalizuj"](m)
                if u not in linki:
                    linki[u] = ""
                    nowe += 1
                if tekst and tekst not in linki[u]:
                    linki[u] = (linki[u] + " " + " ".join(tekst.split()))[:600]
        print(f"    +{nowe} aukcji na tej stronie")
        if nowe == 0:
            break
        tempo.pauza(4, 8)
    return linki


def wyglada_na_kod(t):
    return t.count("function(") + t.count("=>") > 5


# Odpowiedzi API AliExpress z danymi aukcji (zbierane przez page.on("response"))
API_PDP = "mtop.aliexpress.pdp.pc.query"
ODPOWIEDZI_API = []


def lap_api(resp):
    if API_PDP in resp.url:
        ODPOWIEDZI_API.append(resp)


def parsuj_jsonp(t):
    t = t.strip()
    if not t.startswith("{"):
        t = t[t.index("(") + 1: t.rindex(")")]
    return json.loads(t)


def wynik_api(item_id):
    """Ostatnia odpowiedź pdp.pc.query dla tej aukcji (dict 'result') albo None."""
    for resp in reversed(ODPOWIEDZI_API):
        try:
            r = parsuj_jsonp(resp.text())["data"]["result"]
        except Exception:
            continue
        pid = str((r.get("PRICE") or {}).get("productId", ""))
        if item_id and pid and pid != item_id:
            continue
        return r
    return None


def html_na_tekst(h):
    h = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", h)
    h = html.unescape(re.sub(r"<[^>]+>", " ", h))
    return "\n".join(" ".join(w.split()) for w in h.splitlines() if w.strip())


def dane_z_api(r, ctx):
    tytul = (r.get("PRODUCT_TITLE") or {}).get("text", "")
    spec = [f"{p.get('attrName')}: {p.get('attrValue', '')}"
            for p in (r.get("PRODUCT_PROP_PC") or {}).get("showedProps", []) if p.get("attrName")]
    warianty = [
        f"{p.get('skuPropertyName', '')}: " + " | ".join(
            v.get("propertyValueDisplayName") or v.get("propertyValueName", "")
            for v in p.get("skuPropertyValues", []))
        for p in (r.get("SKU") or {}).get("skuProperties", [])
    ]
    cena_txt = ((r.get("PRICE") or {}).get("targetSkuPriceInfo") or {}).get("salePriceString", "")
    opis = ""
    url_opisu = (r.get("DESC") or {}).get("pcDescUrl")
    if url_opisu:
        try:
            resp = ctx.request.get(url_opisu, timeout=20000)
            if resp.ok:
                opis = html_na_tekst(resp.text())
        except Exception as e:
            print(f"   (nie udało się pobrać opisu: {str(e).splitlines()[0]})")
    tekst = ("SPECYFIKACJA\n" + "\n".join(spec) + "\n\nWARIANTY\n" + "\n".join(warianty)
             + "\n\nOPIS\n" + opis)
    return {"tytul": tytul, "tekst": tekst[:60000], "cena": cena_txt, "zrodlo": "api"}


JS_PARAMETRY = """() => {
    const out = [];
    for (const dl of document.querySelectorAll('dl')) {
        const dt = dl.querySelectorAll(':scope > dt'), dd = dl.querySelectorAll(':scope > dd');
        if (dt.length && dt.length === dd.length) dt.forEach((e, i) => out.push([e.innerText, dd[i].innerText]));
    }
    for (const tr of document.querySelectorAll('table tr')) {
        const c = tr.querySelectorAll(':scope > th, :scope > td');
        if (c.length === 2) out.push([c[0].innerText, c[1].innerText]);
    }
    return out.map(([k, v]) => [k.trim(), v.trim().replace(/\\s+/g, ' ')])
              .filter(([k, v]) => k && v && k.length < 60 && v.length < 200).slice(0, 80);
}"""


def produkt_ldjson(page):
    """Obiekt schema.org/Product z danych JSON-LD strony (jest w większości sklepów)."""
    try:
        skrypty = page.eval_on_selector_all('script[type="application/ld+json"]',
                                            "els => els.map(e => e.textContent)")
    except Exception:
        return None
    for j in skrypty:
        try:
            d = json.loads(j)
        except Exception:
            continue
        for x in (d if isinstance(d, list) else d.get("@graph", [d]) if isinstance(d, dict) else []):
            typ = x.get("@type") if isinstance(x, dict) else None
            if typ == "Product" or (isinstance(typ, list) and "Product" in typ):
                return x
    return None


def parametry_strony(page, cfg):
    """Pary 'klucz: wartość' – z bloku tekstu wskazanego w konfiguracji sklepu,
    a gdy go nie ma, z tabel i list <dl> na stronie."""
    if cfg.get("parametry"):
        try:
            body = page.inner_text("body")
            poczatek, koniec = cfg["parametry"]
            m = re.search(poczatek + r"(.*?)" + koniec, body, re.S)
            if m:
                pomin = re.compile(cfg.get("pomin_linie", r"^$"))
                linie = [l.strip() for l in m.group(1).splitlines() if l.strip() and not pomin.search(l.strip())]
                return [f"{k}: {v}" for k, v in zip(linie[::2], linie[1::2])]
        except Exception:
            pass
    try:
        return [f"{k}: {v}" for k, v in page.evaluate(JS_PARAMETRY)]
    except Exception:
        return []


def dane_ldjson(page, cfg):
    """Allegro (i inne sklepy z JSON-LD): tytuł, cena i opis z JSON-LD, parametry ze strony.
    Polecane i sponsorowane produkty z reszty strony nie są czytane."""
    produkt = produkt_ldjson(page)
    if not produkt or not produkt.get("name"):
        return None
    oferta = produkt.get("offers") or {}
    if isinstance(oferta, list):
        oferta = oferta[0] if oferta else {}
    kwota = (oferta.get("price") or oferta.get("lowPrice")
             or (oferta.get("priceSpecification") or {}).get("price"))
    cena_txt = f"{str(kwota).replace('.', ',')} zł" if kwota else ""
    opis = produkt.get("description", "")
    tekst = ("SPECYFIKACJA\n" + "\n".join(parametry_strony(page, cfg)) + "\n\nWARIANTY\n\n\nOPIS\n"
             + html_na_tekst(opis if isinstance(opis, str) else ""))
    return {"tytul": html.unescape(str(produkt["name"])), "tekst": tekst[:60000], "cena": cena_txt,
            "zrodlo": "ldjson"}


def dane_ze_strony(page):
    """Stara metoda: cały tekst strony (z polecanymi produktami – mniej dokładna)."""
    tytul = ""
    for sel in ("h1", "[data-pl=product-title]", "title"):
        try:
            tytul = page.inner_text(sel, timeout=3000).strip()
            if tytul:
                break
        except Exception:
            pass
    czesci = []
    for f in page.frames:  # opis bywa w iframe
        if any(s in f.url.lower() for s in CAPTCHA_W_URL):
            continue
        try:
            t = f.inner_text("body", timeout=5000)
        except Exception:
            continue
        if not wyglada_na_kod(t):
            czesci.append(t)
    # warianty (np. "DC3V") często są tylko w atrybutach title/alt przycisków
    try:
        atr = page.eval_on_selector_all(
            "[title],[alt],[aria-label]",
            "els => els.map(e => e.getAttribute('title') || e.getAttribute('alt') || e.getAttribute('aria-label'))",
        )
        czesci.append(" | ".join(a for a in atr if a and len(a) < 80))
    except Exception:
        pass
    return {"tytul": tytul, "tekst": utnij_polecane("\n".join(czesci))[:60000], "zrodlo": "strona"}


def pobierz_aukcje(page, url, headless, tempo):
    ODPOWIEDZI_API.clear()
    if not otworz(page, url, headless, tempo):
        return None
    przewin(page, 8)
    stan = czekaj_na_captche(page, headless, tempo)  # captcha potrafi wyskoczyć w trakcie
    if stan == "pomin":
        return None
    if stan == "rozwiazana":
        ODPOWIEDZI_API.clear()
        if not otworz(page, url, headless, tempo):
            return None
        przewin(page, 8)

    m = re.search(r"/item/(\d+)", url)
    if m:  # AliExpress – czyste dane z API strony
        for _ in range(20):  # do 10 s na odpowiedź
            r = wynik_api(m.group(1))
            if r:
                d = dane_z_api(r, page.context)
                if d["tytul"]:
                    return d
                break
            page.wait_for_timeout(500)
        print("   brak danych z API – biorę tekst strony (mniej dokładnie)")
    else:
        d = dane_ldjson(page, SKLEPY.get(sklep_z_url(url), {}))
        if d:
            return d
        print("   brak danych produktu (JSON-LD) – biorę tekst strony (mniej dokładnie)")

    dane = dane_ze_strony(page)
    if wyglada_na_captche(dane) or (not dane["tytul"] and len(dane["tekst"]) < 1500):
        print("   strona wygląda na pustą / weryfikację – nie zapisuję, spróbuję następnym razem")
        return None
    return dane


def uruchom_przegladarke(pw, a, katalog):
    opcje = dict(
        headless=a.headless, locale="pl-PL", timezone_id="Europe/Warsaw",
        no_viewport=True,
        args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        ignore_default_args=["--enable-automation"],
    )
    if a.chrome:
        opcje["executable_path"] = a.chrome
    try:
        return pw.chromium.launch_persistent_context(str(katalog), **opcje)
    except Exception as e:
        if "SingletonLock" in str(e) or "ProcessSingleton" in str(e) or "already in use" in str(e):
            sys.exit(f"Katalog przeglądarki {katalog.name} jest już używany – ten profil i sklep "
                     "działają w innym oknie terminala. Uruchom inny profil albo poczekaj.")
        raise


# --------------------------------------------------------------------------
# RAPORT
# --------------------------------------------------------------------------

def zapisz_raport(wyniki, nazwa, profil):
    """Jeden raport na profil – wszystkie sklepy razem, do porównania."""
    baza = KATALOG / f"wyniki_{nazwa}"
    with open(baza.with_suffix(".csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ocena", "sklep", "cena", "tytuł", "link", "powody", "fragmenty"])
        for r in wyniki:
            w.writerow([r["ocena"], r["sklep"], r["cena"], r["tytul"], r["url"],
                        " | ".join(r["powody"]), " || ".join(r["cytaty"])])

    wiersze = []
    for r in wyniki:
        kolor = "#d8f5d0" if r["ocena"] >= 8 else "#fff6cc" if r["ocena"] >= 4 else "#f3f3f3"
        wiersze.append(
            f"<tr style='background:{kolor}'><td><b>{r['ocena']}</b></td>"
            f"<td>{html.escape(r['sklep'])}</td>"
            f"<td>{html.escape(r['cena'])}</td>"
            f"<td><a href='{html.escape(r['url'])}' target='_blank'>{html.escape(r['tytul'][:160] or r['url'])}</a>"
            f"<div class='p'>{html.escape(' · '.join(r['powody']))}</div></td>"
            f"<td class='c'>{'<br>'.join(html.escape(c) for c in r['cytaty']) or '–'}</td></tr>"
        )
    ile = {}
    for r in wyniki:
        ile[r["sklep"]] = ile.get(r["sklep"], 0) + 1
    podsum = ", ".join(f"{s}: {n}" for s, n in ile.items()) or "brak"
    baza.with_suffix(".html").write_text(f"""<!doctype html><meta charset="utf-8">
<title>Wyniki – {html.escape(nazwa)}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:20px}} table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:6px;vertical-align:top;font-size:14px}}
.p{{color:#555;font-size:12px;margin-top:4px}} .c{{font-size:12px;font-family:monospace;max-width:520px}}
</style>
<h2>Wyniki: {html.escape(nazwa)} – {len(wyniki)} ofert ({html.escape(podsum)})</h2>
<p>{html.escape(profil['opis'])}</p>
<p>Zielone = mocne trafienie, żółte = do sprawdzenia. W ostatniej kolumnie fragmenty tekstu do weryfikacji.</p>
<table><tr><th>Ocena</th><th>Sklep</th><th>Cena</th><th>Oferta</th><th>Fragmenty</th></tr>
{''.join(wiersze)}</table>""", encoding="utf-8")
    return baza


# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------

def wczytaj_cache(nazwa, sklep):
    f = plik_cache(nazwa, sklep)
    cache = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    zle = [u for u, d in cache.items() if wyglada_na_captche(d)]
    for u in zle:
        del cache[u]
    if zle:
        print(f"{sklep}: usunięto z cache {len(zle)} wpisów, które były stroną captchy.")
    return cache


def ocen_cache(cache, profil, min_ocena):
    wyniki = []
    for u, d in cache.items():
        if stary_wpis(u, d):
            continue
        o, powody, cytaty = ocen(d, profil, u)
        if o >= min_ocena:
            wyniki.append({"url": u, "sklep": sklep_z_url(u), "tytul": d["tytul"], "ocena": o,
                           "powody": powody, "cytaty": cytaty, "cena": d.get("cena") or cena(d["tekst"])})
    wyniki.sort(key=lambda r: -r["ocena"])
    return wyniki


def podglad(d, profil, url, min_ocena):
    """Jedna-dwie linie do terminala po pobraniu aukcji."""
    o, powody, cytaty = ocen(d, profil, url)
    if o == -99:
        print(f"   ✗ odpada ({powody[0]}) – {d['tytul'][:70]}")
        return
    znak = "★" if o >= 8 else "+" if o >= min_ocena else "·"
    print(f"   {znak} ocena {o:+d}  {d.get('cena') or cena(d['tekst'])}  {d['tytul'][:70]}")
    if powody:
        print(f"     {'; '.join(powody)}")
    nap = [c for c in cytaty if "· spec]" in c][:2]
    for c in nap:
        print(f"     {c[:150]}")


def szukaj_w_sklepie(pw, a, nazwa, profil, sklep, frazy, caches):
    """Jedno wyszukiwanie w jednym sklepie: lista wyników → wstępna ocena → aukcje."""
    cache = caches[sklep]
    plik_c = plik_cache(nazwa, sklep)
    ctx = uruchom_przegladarke(pw, a, katalog_przegladarki(nazwa, sklep))
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", lap_api)
    tempo = Tempo(a.tempo)
    try:
        linki = {}
        for fr in frazy:
            print(f"\n[{sklep}] Fraza: {fr}")
            for u, karta in zbierz_linki(page, sklep, fr, a.strony, a.headless, tempo).items():
                linki.setdefault(u, karta)
        kandydaci = {u: k for u, k in linki.items() if u not in cache}
        if a.odswiez:  # stare wpisy AliExpress (tekst strony z reklamami)
            for u, d in cache.items():
                if stary_wpis(u, d):
                    kandydaci.setdefault(u, d.get("tytul", ""))
        # wstępna ocena po tytule z listy – nie otwieramy aukcji, które już
        # w tytule mówią np. "220V", a najlepsze kandydatki idą na początek
        if SKLEPY[sklep].get("bez_oceny_listy"):
            ocenione = [((0, ["sklep nie pokazuje opisów na liście"]), u, k) for u, k in kandydaci.items()]
        else:
            ocenione = sorted(((ocen_tytul(k, profil), u, k) for u, k in kandydaci.items()),
                              key=lambda x: -x[0][0])
        do_pobrania = [u for (o, _), u, _ in ocenione if o >= a.prog_listy][: a.max]
        pominiete = [(o, pw_, k) for (o, pw_), u, k in ocenione if o < a.prog_listy]
        print(f"\n[{sklep}] Znaleziono {len(linki)} ofert: {len(linki) - len(kandydaci)} już w cache, "
              f"{len(pominiete)} odrzuconych po tytule, do otwarcia: {len(do_pobrania)}")
        for o, pw_, k in pominiete[:5]:
            print(f"   ✗ {o:+d} {' '.join(k.split())[:70]}  [{', '.join(pw_)}]")
        if len(pominiete) > 5:
            print(f"   … i {len(pominiete) - 5} więcej")

        for i, u in enumerate(do_pobrania, 1):
            print(f"[{sklep} {i}/{len(do_pobrania)}] {u}")
            try:
                d = pobierz_aukcje(page, u, a.headless, tempo)
                if d:
                    cache[u] = d
                    plik_c.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                    podglad(d, profil, u, a.min_ocena)
                    # raport na bieżąco – można odświeżać w przeglądarce
                    zapisz_raport(ocen_wszystko(caches, profil, a.min_ocena), nazwa, profil)
            except KoniecSzukania:
                raise
            except Exception as e:
                print(f"   błąd: {str(e).splitlines()[0]}")
            if i < len(do_pobrania):
                tempo.po_aukcji(a.przerwa_co)
    finally:
        plik_c.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        try:
            ctx.close()
        except Exception:
            pass


def ocen_wszystko(caches, profil, min_ocena):
    wyniki = []
    for cache in caches.values():
        wyniki += ocen_cache(cache, profil, min_ocena)
    wyniki.sort(key=lambda r: -r["ocena"])
    return wyniki


def main():
    ap = argparse.ArgumentParser(description="Szukacz produktów: AliExpress, Allegro")
    ap.add_argument("--sklep", nargs="+", choices=list(SKLEPY) + ["wszystkie"],
                    help="sklep(y) do przeszukania; domyślnie 'sklepy' z profilu albo aliexpress")
    ap.add_argument("--profil", help="nazwa profilu z profile.toml (domyślnie pierwszy)")
    ap.add_argument("--lista", action="store_true", help="pokaż profile i zakończ")
    ap.add_argument("--frazy", nargs="+", help="własne frazy zamiast tych z profilu")
    ap.add_argument("--wymagane", nargs="+", help="jednorazowy profil: wzorce, które aukcja musi mieć")
    ap.add_argument("--plus", nargs="+", help="jednorazowy profil: wzorce na plus (+3 tytuł/spec, +1 opis)")
    ap.add_argument("--minus", nargs="+", help="jednorazowy profil: wzorce na minus (−5 tytuł/spec, −2 opis)")
    ap.add_argument("--strony", type=int, default=2, help="ile stron wyników na frazę")
    ap.add_argument("--max", type=int, default=40, help="maks. liczba NOWYCH ofert do otwarcia (w każdym sklepie)")
    ap.add_argument("--prog-listy", type=int, default=0,
                    help="otwieraj tylko oferty, których tytuł na liście wyników ma ≥ N pkt "
                         "(-99 = otwieraj wszystkie)")
    ap.add_argument("--min-ocena", type=int, default=3, help="nie pokazuj ofert poniżej tej oceny")
    ap.add_argument("--tempo", type=float, default=1.0,
                    help="mnożnik przerw: 2 = dwa razy wolniej (mniej captchy)")
    ap.add_argument("--przerwa-co", type=int, default=12,
                    help="co ile ofert dłuższa przerwa 1–2,5 min (0 = wyłącz)")
    ap.add_argument("--odswiez", action="store_true",
                    help="pobierz ponownie WSZYSTKIE stare wpisy AliExpress z cache (zapisane jako tekst strony)")
    ap.add_argument("--tylko-ocena", action="store_true", help="tylko przelicz oceny z cache")
    ap.add_argument("--przegladarka", action="store_true",
                    help="tylko otwórz przeglądarkę z głównym profilem (zaloguj się, zaakceptuj cookies)")
    ap.add_argument("--chrome", metavar="ŚCIEŻKA",
                    help="użyj innej przeglądarki, np. /usr/bin/chromium (pacman -S chromium)")
    ap.add_argument("--cicho", action="store_true", help="bez dźwięku i powiadomień przy captchy")
    ap.add_argument("--headless", action="store_true", help="bez okna (captchy nie da się wtedy rozwiązać)")
    a = ap.parse_args()

    global CICHO
    CICHO = a.cicho
    profile = wczytaj_profile()
    if a.lista:
        for n, p in profile.items():
            sk = ", ".join(p["sklepy"]) or "aliexpress"
            print(f"  {n:<20} {p['opis']}  ({len(p['frazy'])} fraz, {len(p['reguly'])} reguł; sklepy: {sk})")
            for s in SKLEPY:
                f = plik_cache(n, s)
                if f.exists():
                    ile = len(json.loads(f.read_text(encoding="utf-8")))
                    kiedy = time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))
                    print(f"  {'':<20}   {s}: {ile} ofert w cache, ostatnio {kiedy}")
        return

    if a.wymagane or a.plus or a.minus:
        if not a.frazy and not a.tylko_ocena:
            sys.exit("Profil z linii poleceń wymaga --frazy")
        nazwa, profil = "wlasny", profil_z_cli(a)
    else:
        nazwa = a.profil or next(iter(profile))
        if nazwa not in profile:
            sys.exit(f"Nie ma profilu '{nazwa}'. Dostępne: {', '.join(profile)}")
        profil = profile[nazwa]
    if a.sklep and "wszystkie" in a.sklep:
        sklepy = list(SKLEPY)
    else:
        sklepy = a.sklep or profil["sklepy"] or ["aliexpress"]
    print(f"Profil: {nazwa} – {profil['opis']}\nSklepy: {', '.join(sklepy)}")

    DANE.mkdir(exist_ok=True)
    # raport obejmuje wszystkie sklepy, w których ten profil kiedykolwiek szukał
    caches = {s: wczytaj_cache(nazwa, s) for s in SKLEPY if s in sklepy or plik_cache(nazwa, s).exists()}

    if a.przegladarka or not a.tylko_ocena:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            sys.exit("Brak Playwright. Na Archu: sudo pacman -S python-playwright\n"
                     "potem: python -m playwright install chromium")

        with sync_playwright() as pw:
            if a.przegladarka:
                ctx = uruchom_przegladarke(pw, a, PROFIL_PRZEGLADARKI)
                for i, s in enumerate(sklepy):
                    pg = ctx.pages[0] if i == 0 and ctx.pages else ctx.new_page()
                    pg.goto(SKLEPY[s]["start"])
                input("Przeglądarka otwarta (główny profil). Zaloguj się / zaakceptuj cookies, potem Enter… ")
                print("Uwaga: profile, które już mają swoją kopię w dane/, jej nie odświeżą – "
                      "usuń dane/przegladarka_<profil>_<sklep>/, żeby skopiować na nowo.")
                ctx.close()
                return
            try:
                for s in sklepy:
                    frazy = a.frazy or profil["frazy_sklep"].get(s) or profil["frazy"]
                    try:
                        szukaj_w_sklepie(pw, a, nazwa, profil, s, frazy, caches)
                    except (KeyboardInterrupt, KoniecSzukania):
                        raise
                    except Exception as e:
                        # błąd w jednym sklepie (np. zamknięte okno) nie przerywa pozostałych
                        print(f"\n[{s}] przerwano z powodu błędu: {str(e).splitlines()[0]}")
            except (KeyboardInterrupt, KoniecSzukania):
                print("\nPrzerwano – robię raport z tego, co już pobrane.")

    wyniki = ocen_wszystko(caches, profil, a.min_ocena)
    baza = zapisz_raport(wyniki, nazwa, profil)
    print(f"\nGotowe: {len(wyniki)} pasujących ofert → {baza.name}.html, {baza.name}.csv")
    stare = sum(1 for c in caches.values() for u, d in c.items() if stary_wpis(u, d))
    if stare:
        print(f"(Pominięto {stare} starych wpisów bez danych z API – pobierz je ponownie: --odswiez)")
    for r in wyniki[:10]:
        print(f"  {r['ocena']:>3}  [{r['sklep']}] {r['tytul'][:75]}\n       {r['url']}")


if __name__ == "__main__":
    main()
