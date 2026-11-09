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
    python szukaj_zarowek.py --frazy "TP4056 type-c" --wymagane TP4056 --plus "type-?c" --minus "micro ?usb"

Przykłady:
    python szukaj_zarowek.py --lista                 # pokaż dostępne profile
    python szukaj_zarowek.py                         # profil zarowka, AliExpress
    python szukaj_zarowek.py --profil filament --sklep allegro
    python szukaj_zarowek.py --tylko-ocena           # przelicz z cache, bez internetu
    python szukaj_zarowek.py --przegladarka          # otwórz okno, żeby się zalogować

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
import sys
import time
import tomllib
from pathlib import Path
from urllib.parse import quote_plus

KATALOG = Path(__file__).resolve().parent
PLIK_PROFILI = KATALOG / "profile.toml"
CACHE = KATALOG / "cache_aukcji.json"
PROFIL_PRZEGLADARKI = KATALOG / "profil-przegladarki"

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
        "link": re.compile(r"allegro\.pl/oferta/([\w-]+)"),
        "normalizuj": lambda m: f"https://allegro.pl/oferta/{m.group(1)}",
    },
}

# Po czym poznać stronę weryfikacji. AliExpress przekierowuje na
# .../_____tmd_____/punish i wstawia reCAPTCHA w ramce, Allegro używa DataDome.
# (Nie sprawdzamy samego "recaptcha" w adresach ramek – niewidoczna reCAPTCHA
# bywa też na zwykłych stronach i skrypt czekałby w nieskończoność.)
CAPTCHA_W_URL = ("_____tmd_____", "/punish", "captcha-delivery.com")
CAPTCHA_W_TEKSCIE = ("we need to check if you are a robot", "nie jestem robotem",
                     "slide to verify", "przesuń suwak", "verify you are human",
                     "unusual traffic", "potwierdź, że nie jesteś robotem",
                     "jesteś robotem", "access is temporarily restricted")


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
                 "cytuj": bool(r.get("cytuj", False))}
                for r in p.get("reguly", [])
            ]
            wymagane = [re.compile(rozwin(w), re.I) for w in p.get("wymagane", [])]
        except re.error as e:
            sys.exit(f"{PLIK_PROFILI.name}, profil '{nazwa}': błędny wzorzec – {e}")
        except KeyError as e:
            sys.exit(f"{PLIK_PROFILI.name}, profil '{nazwa}': reguła bez pola {e}")
        profile[nazwa] = {"opis": p.get("opis", ""), "frazy": p.get("frazy", []),
                          "wymagane": wymagane, "reguly": reguly}
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
    reguly = [{"nazwa": f"+ {w}", "rx": rx(w), "tytul": 3, "opis": 1, "cytuj": True} for w in a.plus or []]
    reguly += [{"nazwa": f"− {w}", "rx": rx(w), "tytul": -5, "opis": -2, "cytuj": True} for w in a.minus or []]
    return {"opis": "profil z linii poleceń", "frazy": a.frazy or [],
            "wymagane": [rx(w) for w in a.wymagane or []], "reguly": reguly}


# --------------------------------------------------------------------------
# OCENA
# --------------------------------------------------------------------------

def fragment(tekst, m, szer=70):
    a, b = max(0, m.start() - szer), min(len(tekst), m.end() + szer)
    return ("…" if a else "") + " ".join(tekst[a:b].split()) + ("…" if b < len(tekst) else "")


def ocen(tytul, tekst, profil):
    calosc = f"{tytul}\n{tekst}"
    for wym in profil["wymagane"]:
        if not wym.search(calosc):
            return -99, ["brak wymaganego: " + wym.pattern], []
    wynik, powody, cytaty = 0, [], []
    for r in profil["reguly"]:
        if r["rx"].search(tytul):
            if r["tytul"]:
                wynik += r["tytul"]
                powody.append(f"{r['nazwa']} w tytule ({r['tytul']:+d})")
        elif r["opis"] and r["rx"].search(tekst):
            wynik += r["opis"]
            powody.append(f"{r['nazwa']} w opisie ({r['opis']:+d})")
        if r["cytuj"]:
            for m in list(r["rx"].finditer(tekst))[:3]:
                cytaty.append(f"[{r['nazwa']}] {fragment(tekst, m)}")
    return wynik, powody, cytaty


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


def jest_captcha(page):
    try:
        urle = [page.url] + [f.url for f in page.frames]
        if any(s in u.lower() for u in urle for s in CAPTCHA_W_URL):
            return True
        for f in page.frames:
            try:
                t = f.inner_text("body", timeout=1500)[:3000].lower()
            except Exception:
                continue
            if any(s in t for s in CAPTCHA_W_TEKSCIE):
                return True
    except Exception:
        # strona akurat się przeładowuje – sprawdzimy za chwilę
        return None
    return False


def czekaj_na_captche(page, headless, tempo, limit_min=20):
    """Zwraca True, jeśli była captcha (wtedy stronę trzeba pobrać ponownie)."""
    stan = jest_captcha(page)
    if not stan:
        return False
    if headless:
        sys.exit("\nSklep pokazał captchę, a w trybie --headless nie da się jej rozwiązać. "
                 "Uruchom bez --headless.")
    print("\a\n>>> CAPTCHA – rozwiąż ją w oknie przeglądarki. Skrypt czeka i sam ruszy, "
          "gdy weryfikacja zniknie.")
    start = time.time()
    czyste = 0
    while czyste < 3:  # 3 kolejne sprawdzenia bez captchy = naprawdę przeszło
        time.sleep(2)
        stan = jest_captcha(page)
        czyste = czyste + 1 if stan is False else 0
        if time.time() - start > limit_min * 60:
            input(f">>> Minęło {limit_min} min. Naciśnij Enter, żeby kontynuować… ")
            break
    print(">>> Weryfikacja zaliczona, odczekuję chwilę i jadę dalej.")
    tempo.zwolnij()
    tempo.pauza(8, 15)
    return True


def otworz(page, url, headless, tempo, prob=3):
    """Otwiera stronę; jeśli była captcha, po jej rozwiązaniu ładuje stronę od nowa."""
    for _ in range(prob):
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        tempo.pauza(1.5, 3)
        if not czekaj_na_captche(page, headless, tempo):
            return True
    print("   nie udało się otworzyć strony bez captchy – pomijam")
    return False


def przewin(page, krokow=12):
    for _ in range(krokow):
        page.mouse.wheel(0, random.randint(500, 1100))
        time.sleep(random.uniform(0.3, 0.9))


def zbierz_linki(page, sklep, fraza, strony, headless, tempo):
    cfg = SKLEPY[sklep]
    linki = []
    for s in range(1, strony + 1):
        url = cfg["url_wyszukiwania"](fraza, s)
        print(f"  wyniki: {url}")
        if not otworz(page, url, headless, tempo):
            break
        przewin(page, 8)
        hrefy = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        nowe = 0
        for h in hrefy:
            m = cfg["link"].search(h)
            if m:
                u = cfg["normalizuj"](m)
                if u not in linki:
                    linki.append(u)
                    nowe += 1
        print(f"    +{nowe} aukcji")
        if nowe == 0:
            break
        tempo.pauza(4, 8)
    return linki


def wyglada_na_kod(t):
    return t.count("function(") + t.count("=>") > 5


def pobierz_aukcje(page, url, headless, tempo):
    if not otworz(page, url, headless, tempo):
        return None
    przewin(page, 15)  # opis na AliExpress doczytuje się dopiero po przewinięciu
    if czekaj_na_captche(page, headless, tempo):  # captcha potrafi wyskoczyć w trakcie
        if not otworz(page, url, headless, tempo):
            return None
        przewin(page, 15)
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
    dane = {"tytul": tytul, "tekst": utnij_polecane("\n".join(czesci))[:60000]}
    if wyglada_na_captche(dane) or (not tytul and len(dane["tekst"]) < 1500):
        print("   strona wygląda na pustą / weryfikację – nie zapisuję, spróbuję następnym razem")
        return None
    return dane


def uruchom_przegladarke(pw, a):
    opcje = dict(
        headless=a.headless, locale="pl-PL", timezone_id="Europe/Warsaw",
        no_viewport=True,
        args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        ignore_default_args=["--enable-automation"],
    )
    if a.chrome:
        opcje["executable_path"] = a.chrome
    return pw.chromium.launch_persistent_context(str(PROFIL_PRZEGLADARKI), **opcje)


# --------------------------------------------------------------------------
# RAPORT
# --------------------------------------------------------------------------

def zapisz_raport(wyniki, nazwa, profil, sklep):
    baza = KATALOG / f"wyniki_{nazwa}_{sklep}"
    with open(baza.with_suffix(".csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ocena", "cena", "tytuł", "link", "powody", "fragmenty"])
        for r in wyniki:
            w.writerow([r["ocena"], r["cena"], r["tytul"], r["url"],
                        " | ".join(r["powody"]), " || ".join(r["cytaty"])])

    wiersze = []
    for r in wyniki:
        kolor = "#d8f5d0" if r["ocena"] >= 8 else "#fff6cc" if r["ocena"] >= 4 else "#f3f3f3"
        wiersze.append(
            f"<tr style='background:{kolor}'><td><b>{r['ocena']}</b></td>"
            f"<td>{html.escape(r['cena'])}</td>"
            f"<td><a href='{html.escape(r['url'])}' target='_blank'>{html.escape(r['tytul'][:160] or r['url'])}</a>"
            f"<div class='p'>{html.escape(' · '.join(r['powody']))}</div></td>"
            f"<td class='c'>{'<br>'.join(html.escape(c) for c in r['cytaty']) or '–'}</td></tr>"
        )
    baza.with_suffix(".html").write_text(f"""<!doctype html><meta charset="utf-8">
<title>Wyniki – {html.escape(nazwa)} ({sklep})</title>
<style>
body{{font-family:system-ui,sans-serif;margin:20px}} table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:6px;vertical-align:top;font-size:14px}}
.p{{color:#555;font-size:12px;margin-top:4px}} .c{{font-size:12px;font-family:monospace;max-width:520px}}
</style>
<h2>Wyniki: {html.escape(nazwa)} – {sklep} – {len(wyniki)} aukcji</h2>
<p>{html.escape(profil['opis'])}</p>
<p>Zielone = mocne trafienie, żółte = do sprawdzenia. W ostatniej kolumnie fragmenty tekstu do weryfikacji.</p>
<table><tr><th>Ocena</th><th>Cena</th><th>Aukcja</th><th>Fragmenty</th></tr>
{''.join(wiersze)}</table>""", encoding="utf-8")
    return baza


# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Szukacz produktów na AliExpress / Allegro")
    ap.add_argument("--sklep", choices=list(SKLEPY), default="aliexpress")
    ap.add_argument("--profil", help="nazwa profilu z profile.toml (domyślnie pierwszy)")
    ap.add_argument("--lista", action="store_true", help="pokaż profile i zakończ")
    ap.add_argument("--frazy", nargs="+", help="własne frazy zamiast tych z profilu")
    ap.add_argument("--wymagane", nargs="+", help="jednorazowy profil: wzorce, które aukcja musi mieć")
    ap.add_argument("--plus", nargs="+", help="jednorazowy profil: wzorce na plus (+3 tytuł / +1 opis)")
    ap.add_argument("--minus", nargs="+", help="jednorazowy profil: wzorce na minus (−5 / −2)")
    ap.add_argument("--strony", type=int, default=2, help="ile stron wyników na frazę")
    ap.add_argument("--max", type=int, default=40, help="maks. liczba NOWYCH aukcji do otwarcia")
    ap.add_argument("--min-ocena", type=int, default=3, help="nie pokazuj aukcji poniżej tej oceny")
    ap.add_argument("--tempo", type=float, default=1.0,
                    help="mnożnik przerw: 2 = dwa razy wolniej (mniej captchy)")
    ap.add_argument("--przerwa-co", type=int, default=12,
                    help="co ile aukcji dłuższa przerwa 1–2,5 min (0 = wyłącz)")
    ap.add_argument("--tylko-ocena", action="store_true", help="tylko przelicz oceny z cache")
    ap.add_argument("--przegladarka", action="store_true",
                    help="tylko otwórz przeglądarkę z profilem (zaloguj się, zaakceptuj cookies)")
    ap.add_argument("--chrome", metavar="ŚCIEŻKA",
                    help="użyj innej przeglądarki, np. /usr/bin/chromium (pacman -S chromium)")
    ap.add_argument("--headless", action="store_true", help="bez okna (captchy nie da się wtedy rozwiązać)")
    a = ap.parse_args()

    profile = wczytaj_profile()
    if a.lista:
        for n, p in profile.items():
            print(f"  {n:<14} {p['opis']}  ({len(p['frazy'])} fraz, {len(p['reguly'])} reguł)")
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
    frazy = a.frazy or profil["frazy"]
    print(f"Profil: {nazwa} – {profil['opis']}")

    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    zle = [u for u, d in cache.items() if wyglada_na_captche(d)]
    for u in zle:
        del cache[u]
    if zle:
        print(f"Usunięto z cache {len(zle)} wpisów, które były stroną captchy – zostaną pobrane ponownie.")

    if a.przegladarka or not a.tylko_ocena:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            sys.exit("Brak Playwright. Na Archu: sudo pacman -S python-playwright\n"
                     "potem: python -m playwright install chromium")

        with sync_playwright() as pw:
            ctx = uruchom_przegladarke(pw, a)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            if a.przegladarka:
                page.goto("https://www.aliexpress.com" if a.sklep == "aliexpress" else "https://allegro.pl")
                input("Przeglądarka otwarta. Zaloguj się / zaakceptuj cookies, potem Enter, żeby zamknąć… ")
                ctx.close()
                return

            tempo = Tempo(a.tempo)
            try:
                linki = []
                for fr in frazy:
                    print(f"\nFraza: {fr}")
                    for u in zbierz_linki(page, a.sklep, fr, a.strony, a.headless, tempo):
                        if u not in linki:
                            linki.append(u)
                do_pobrania = [u for u in linki if u not in cache][: a.max]
                print(f"\nZnaleziono {len(linki)} aukcji, nowych do otwarcia: {len(do_pobrania)}")

                for i, u in enumerate(do_pobrania, 1):
                    print(f"[{i}/{len(do_pobrania)}] {u}")
                    try:
                        d = pobierz_aukcje(page, u, a.headless, tempo)
                        if d:
                            cache[u] = d
                            CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                    except Exception as e:
                        print(f"   błąd: {e}")
                    if i < len(do_pobrania):
                        tempo.po_aukcji(a.przerwa_co)
            except KeyboardInterrupt:
                print("\nPrzerwano – robię raport z tego, co już pobrane.")
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass

    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    wyniki = []
    for u, d in cache.items():
        if a.sklep not in u:
            continue
        o, powody, cytaty = ocen(d["tytul"], d["tekst"], profil)
        if o >= a.min_ocena:
            wyniki.append({"url": u, "tytul": d["tytul"], "ocena": o, "powody": powody,
                           "cytaty": cytaty, "cena": cena(d["tekst"])})
    wyniki.sort(key=lambda r: -r["ocena"])
    baza = zapisz_raport(wyniki, nazwa, profil, a.sklep)
    print(f"\nGotowe: {len(wyniki)} pasujących aukcji → {baza.name}.html, {baza.name}.csv")
    for r in wyniki[:10]:
        print(f"  {r['ocena']:>3}  {r['tytul'][:80]}\n       {r['url']}")


if __name__ == "__main__":
    main()
