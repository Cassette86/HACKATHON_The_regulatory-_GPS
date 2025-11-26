#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Scraper "maxi" pour remplir :
- EU.db   : textes principaux EU (tu peux ajouter des URLs)
- USA.db  : toutes les FMVSS (49 CFR Part 571) via ecfr.io
- India.db: catalogue complet des AIS (toutes les pages)
- China.db: URLs à compléter
- Japan.db: URLs principales MLIT (à compléter si besoin)

Prérequis :
    pip install requests beautifulsoup4
"""

import sqlite3
import time
import random
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent

DB_PATHS = {
    "EU": BASE_DIR / "EU.db",
    "USA": BASE_DIR / "USA.db",
    "India": BASE_DIR / "India.db",
    "China": BASE_DIR / "China.db",
    "Japan": BASE_DIR / "Japan.db",
    "France": BASE_DIR / "France.db",
    "UK": BASE_DIR / "UK.db",
}


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

# ---------------------------------------------------------------------------
# 1. Utils BDD
# ---------------------------------------------------------------------------

def init_db():
    """Crée les tables 'regulations' dans chaque base si besoin."""
    for region, db_path in DB_PATHS.items():
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS regulations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT,
                source_url TEXT UNIQUE,
                content    TEXT
            )
            """
        )
        conn.commit()
        conn.close()
        print(f"[INFO] Base initialisée : {db_path}")


def save_regulation(region: str, title: str, source_url: str, content: str | None):
    """
    Sauvegarde (ou met à jour) une régulation dans la base du pays.
    - Si l'URL n'existe pas => INSERT
    - Si l'URL existe mais content vide => UPDATE
    """
    db_path = DB_PATHS[region]
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Insert si pas encore présent
    c.execute(
        """
        INSERT OR IGNORE INTO regulations (title, source_url, content)
        VALUES (?, ?, ?)
        """,
        (title, source_url, content),
    )

    # Si déjà présent et qu'on a maintenant du contenu, on met à jour
    if content:
        c.execute(
            """
            UPDATE regulations
            SET content = ?
            WHERE source_url = ?
            AND (content IS NULL OR content = '')
            """,
            (content, source_url),
        )

    conn.commit()
    conn.close()


def fetch_html(url: str, timeout: int = 30) -> str | None:
    """GET simple avec gestion des erreurs et User-Agent."""
    try:
        print(f"[GET] {url}")
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"[ERREUR] Impossible de récupérer {url} : {e}")
        return None


def scrape_text_page(region: str, url: str, title_hint: str | None = None):
    """
    Récupère tout le texte brut d'une page HTML et l'enregistre dans la DB du pays.
    """
    html = fetch_html(url)
    if not html:
        return

    soup = BeautifulSoup(html, "html.parser")
    page_title = title_hint or (soup.title.get_text(strip=True) if soup.title else url)

    # Texte brut (simple mais efficace pour la recherche plein texte)
    text = soup.get_text("\n", strip=True)

    save_regulation(region, page_title, url, text)
    print(f"[OK] {region} : {page_title} ({len(text)} caractères)")
    time.sleep(random.uniform(1.0, 2.5))


# ---------------------------------------------------------------------------
# 2. 🇪🇺 Scraper basique EU (liste fixe de gros textes à enrichir)
# ---------------------------------------------------------------------------

EU_URLS = [
    # Règlement (UE) 2018/858 - type approval véhicules
    "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32018R0858",
    # Règlement (UE) 2019/2144 - General Safety Regulation (ADAS, etc.)
    "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32019R2144",
    # Tu peux ajouter ici d'autres textes importants si tu veux
]


def scrape_eu():
    print("\n================= 🇪🇺 Scraping EU =================")
    for url in EU_URLS:
        scrape_text_page("EU", url)


# ---------------------------------------------------------------------------
# 3. 🇺🇸 FMVSS (49 CFR Part 571) via ecfr.io
# ---------------------------------------------------------------------------

USA_INDEX_URL = "https://ecfr.io/Title-49/Part-571"
USA_SECTION_PREFIX = "/Title-49/Section-571."


def scrape_usa_fmvss():
    """
    1) Récupère la page index Part 571 sur ecfr.io
    2) Trouve tous les liens /Title-49/Section-571.xxx
    3) Télécharge chaque section et l'enregistre dans USA.db
    """
    print("\n================= 🇺🇸 Scraping USA (FMVSS) =================")
    html = fetch_html(USA_INDEX_URL)
    if not html:
        return

    soup = BeautifulSoup(html, "html.parser")

    links = soup.select(f"a[href^='{USA_SECTION_PREFIX}']")
    print(f"[INFO] {len(links)} sections FMVSS trouvées sur l'index.")

    for a in links:
        href = a.get("href")
        if not href:
            continue

        section_url = urljoin(USA_INDEX_URL, href)
        section_title = a.get_text(" ", strip=True) or section_url

        print(f"[INFO] FMVSS : {section_title}")
        scrape_text_page("USA", section_url, title_hint=section_title)


# ---------------------------------------------------------------------------
# 4. 🇮🇳 AIS – Ministry of Road Transport & Highways (morth.nic.in)
# ---------------------------------------------------------------------------

INDIA_AIS_BASE = "https://morth.nic.in/ais"


def parse_ais_table(soup: BeautifulSoup):
    """
    Dans la page AIS, trouve la table "Automotive Industry Standards (AIS)"
    et enregistre chaque ligne (AIS code + Subject + PDF) dans India.db.
    """
    tables = soup.find_all("table")
    target_table = None

    for table in tables:
        text = table.get_text(" ", strip=True)
        if "Automotive Industry Standards (AIS)" in text:
            target_table = table
            break

    if not target_table:
        print("[WARN] Table AIS non trouvée sur cette page.")
        return

    tbody = target_table.find("tbody") or target_table
    rows = tbody.find_all("tr")

    count = 0
    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue

        # D'après le site : [N°, AIS Code, Subject, Status, Download, Date]
        cells = [td.get_text(" ", strip=True) for td in tds]
        # On essaie de rester robuste si la structure varie un peu
        try:
            ais_code = cells[1]
            subject = cells[2]
            status = cells[3] if len(cells) > 3 else ""
            date_str = cells[-1]
        except IndexError:
            continue

        pdf_tag = tr.find("a", href=True)
        pdf_url = urljoin(INDIA_AIS_BASE, pdf_tag["href"]) if pdf_tag else INDIA_AIS_BASE

        title = f"{ais_code} - {subject}".strip()

        # On stocke les métadonnées dans 'content' (le PDF reste à parser si tu veux aller plus loin)
        content_lines = [
            f"AIS code: {ais_code}",
            f"Subject: {subject}",
            f"Status: {status}",
            f"Date: {date_str}",
            f"PDF: {pdf_url}",
        ]
        content = "\n".join(content_lines)

        save_regulation("India", title, pdf_url, content)
        count += 1

    print(f"[OK] {count} normes AIS ajoutées / mises à jour sur cette page.")

# ---------------------------------------------------------------------------
# 🇫🇷 France – quelques textes clés sur Legifrance
# ---------------------------------------------------------------------------

FRANCE_URLS = [
    # Code de la route (version consolidée)
    "https://www.legifrance.gouv.fr/codes/id/LEGITEXT000006074228/",
    # Tu peux rajouter d'autres actes ici si besoin, par ex. :
    # - Arrêtés sur l'éclairage, le contrôle technique, etc.
    # "https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000000571356",  # exemple
]


def scrape_france():
    print("\n================= 🇫🇷 Scraping France (liste fixe) =================")
    for url in FRANCE_URLS:
        scrape_text_page("France", url)




def scrape_india_ais():
    """
    Crawl toutes les pages AIS (pagination ?page=N), et enregistre
    chaque entrée dans India.db.
    """
    print("\n================= 🇮🇳 Scraping India (AIS) =================")

    to_visit = {INDIA_AIS_BASE}
    visited: set[str] = set()

    while to_visit:
        url = to_visit.pop()
        if url in visited:
            continue
        visited.add(url)

        html = fetch_html(url)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
        print(f"[INFO] Traitement de la page AIS : {url}")
        parse_ais_table(soup)

        # Pagination : on cherche les liens avec '?page=' dans l'URL
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "ais?page=" in href:
                full = urljoin(url, href)
                if full not in visited:
                    to_visit.add(full)

        # Petite pause
        time.sleep(random.uniform(1.0, 2.0))


# ---------------------------------------------------------------------------
# 🇬🇧 UK – quelques textes clés sur legislation.gov.uk
# ---------------------------------------------------------------------------

UK_URLS = [
    # The Road Traffic Act 1988 (cadre général)
    "https://www.legislation.gov.uk/ukpga/1988/52/contents",
    # The Road Vehicles (Construction and Use) Regulations 1986
    "https://www.legislation.gov.uk/uksi/1986/1078/contents/made",
    # The Road Vehicles Lighting Regulations 1989
    "https://www.legislation.gov.uk/uksi/1989/1796/contents/made",
    # Tu peux ajouter d'autres textes si besoin (MOT, type approval, etc.)
]


def scrape_uk():
    print("\n================= 🇬🇧 Scraping UK (liste fixe) =================")
    for url in UK_URLS:
        scrape_text_page("UK", url)



# ---------------------------------------------------------------------------
# 5. 🇨🇳 & 🇯🇵 – URLs à compléter (scrape simple)
# ---------------------------------------------------------------------------

CHINA_URLS = [
    # TODO: ajoute ici des URLs officielles des ministères chinois
    # (ex: Ministère de l'Écologie et de l'Environnement pour bruit / émissions)
    # Exemple (à adapter/compléter) :
    # "https://www.mee.gov.cn/xxxx/xxxx.html",
]

JAPAN_URLS = [
    # Page générale sur l'inspection des véhicules (contexte réglementation)
    "https://www.mlit.go.jp/english/inspect/car09e.html",
    # Exemples de pages "Safety Regulations for Road Vehicles" (appels à commentaires)
    "https://www.mlit.go.jp/english/mot_news/mot_news_990902.html",
    "https://www.mlit.go.jp/english/mot_news/mot_news_000627.html",
    # Tu peux ajouter ici d'autres pages importantes
]


def scrape_china():
    print("\n================= 🇨🇳 Scraping China (liste fixe) =================")
    for url in CHINA_URLS:
        scrape_text_page("China", url)


def scrape_japan():
    print("\n================= 🇯🇵 Scraping Japan (liste fixe) =================")
    for url in JAPAN_URLS:
        scrape_text_page("Japan", url)


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------

def main():
    init_db()

    scrape_eu()
    scrape_usa_fmvss()
    scrape_india_ais()
    scrape_china()
    scrape_japan()
    scrape_france()   # <--- ajouter ici
    scrape_uk()       # <--- on ajoute la fonction UK juste après


    print("\n✅ Scraping terminé. Tu peux maintenant relancer search_all.py pour tester.")


if __name__ == "__main__":
    main()
