#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Scraper "maxi" pour remplir :
- EU.db   : textes principaux EU (tu peux ajouter des URLs)
- USA.db  : toutes les FMVSS (49 CFR Part 571) via ecfr.io
- India.db: catalogue complet des AIS (toutes les pages) + texte PDF
- China.db: URLs à compléter
- Japan.db: URLs principales MLIT (à compléter si besoin)
- France.db / UK.db : pages et PDF liés

Prérequis :
    pip install requests beautifulsoup4 pdfminer.six
"""

import sqlite3
import time
import random
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# >>> pour l'extraction de texte PDF
from io import BytesIO
from pdfminer.high_level import extract_text as pdf_extract_text

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
    - Dans tous les cas, si 'content' n'est pas None, on remplace le contenu
      (permet d'enrichir plus tard avec le texte PDF, par ex.)
    """
    db_path = DB_PATHS[region]
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Insert si pas encore présent (avec content éventuellement nul)
    c.execute(
        """
        INSERT OR IGNORE INTO regulations (title, source_url, content)
        VALUES (?, ?, ?)
        """,
        (title, source_url, content),
    )

    # >>> Toujours mettre à jour le content si on en fournit un
    if content is not None:
        c.execute(
            """
            UPDATE regulations
            SET title = ?, content = ?
            WHERE source_url = ?
            """,
            (title, content, source_url),
        )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 2. Utils HTTP / PDF
# ---------------------------------------------------------------------------

def fetch_html(url: str, timeout: int = 30) -> str | None:
    """GET simple HTML avec gestion des erreurs et User-Agent."""
    try:
        print(f"[GET] {url}")
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"[ERREUR] Impossible de récupérer {url} : {e}")
        return None


def fetch_pdf_bytes(url: str, timeout: int = 60) -> bytes | None:
    """Télécharge un PDF et renvoie les bytes."""
    try:
        print(f"[GET PDF] {url}")
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "pdf" not in ctype and not url.lower().endswith(".pdf"):
            print(f"[WARN] Le contenu ne semble pas être un PDF (Content-Type={ctype})")
        return resp.content
    except requests.RequestException as e:
        print(f"[ERREUR] Impossible de télécharger PDF {url} : {e}")
        return None


def extract_pdf_text(pdf_bytes: bytes) -> str | None:
    """Extrait le texte d'un PDF avec pdfminer.six."""
    try:
        with BytesIO(pdf_bytes) as f:
            text = pdf_extract_text(f)
        if not text:
            print("[WARN] PDF sans texte extractible")
            return None
        text = text.strip()
        return text if text else None
    except Exception as e:
        print(f"[ERREUR] Extraction texte PDF impossible : {e}")
        return None


def pdf_already_saved(region: str, pdf_url: str) -> bool:
    """Vérifie rapidement si un PDF (source_url) existe déjà dans la base."""
    db_path = DB_PATHS[region]
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM regulations WHERE source_url = ? AND content IS NOT NULL AND content != ''",
        (pdf_url,),
    )
    row = c.fetchone()
    conn.close()
    return row is not None


def scrape_pdf_and_save(region: str, pdf_url: str, title_hint: str | None = None):
    """Télécharge un PDF, extrait le texte et l'enregistre dans la base."""
    if pdf_already_saved(region, pdf_url):
        print(f"[SKIP] PDF déjà présent avec contenu : {pdf_url}")
        return

    pdf_bytes = fetch_pdf_bytes(pdf_url)
    if not pdf_bytes:
        return

    text = extract_pdf_text(pdf_bytes)
    if not text:
        return

    filename = pdf_url.split("/")[-1] or pdf_url
    title = title_hint or filename

    save_regulation(region, title, pdf_url, text)
    print(f"[OK] {region} : PDF enregistré {title} ({len(text)} caractères)")
    time.sleep(random.uniform(1.0, 2.5))


# ---------------------------------------------------------------------------
# 3. Scrape HTML + PDF liés sur une page
# ---------------------------------------------------------------------------

def scrape_text_page(region: str, url: str, title_hint: str | None = None):
    """
    Récupère tout le texte brut d'une page HTML et l'enregistre dans la DB du pays.
    Ensuite :
      - cherche les liens <a href="...pdf"> sur la page,
      - télécharge ces PDF et stocke leur texte aussi.
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

    # >>> Chercher les PDF liés sur cette page
    pdf_links: set[tuple[str, str]] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href:
            continue
        full_url = urljoin(url, href)
        if full_url.lower().endswith(".pdf"):
            link_text = a.get_text(" ", strip=True) or full_url.split("/")[-1]
            pdf_links.add((full_url, link_text))

    if pdf_links:
        print(f"[INFO] {len(pdf_links)} lien(s) PDF trouvé(s) sur {url}")
        for pdf_url, link_text in pdf_links:
            pdf_title = f"{page_title} - {link_text}"
            scrape_pdf_and_save(region, pdf_url, pdf_title)

    time.sleep(random.uniform(1.0, 2.5))


# ---------------------------------------------------------------------------
# 4. 🇪🇺 Scraper basique EU (liste fixe de gros textes à enrichir)
# ---------------------------------------------------------------------------

EU_URLS = [
    # Règlement (UE) 2018/858 - type approval véhicules
    "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32018R0858",
    # Règlement (UE) 2019/2144 - General Safety Regulation (ADAS, etc.)
    "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32019R2144",

    # Émissions Euro 5 / Euro 6 véhicules légers
    "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32007R0715",

    # Émissions Euro VI véhicules lourds
    "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32009R0595",
]


def eurlex_pdf_url_from_txt_url(txt_url: str) -> str | None:
    """
    Pour une URL du type:
      https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32018R0858
    on construit l'URL PDF "classique":
      https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32018R0858&from=EN
    """
    if "eur-lex.europa.eu" not in txt_url or "CELEX:" not in txt_url:
        return None
    try:
        celex_part = txt_url.split("CELEX:", 1)[1]
        celex = celex_part.split("&", 1)[0]
        pdf_url = f"https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:{celex}&from=EN"
        return pdf_url
    except Exception:
        return None


def scrape_eu():
    print("\n================= 🇪🇺 Scraping EU =================")
    for url in EU_URLS:
        scrape_text_page("EU", url)

        # >>> Tenter de récupérer aussi le PDF consolidé via le motif CELEX
        pdf_url = eurlex_pdf_url_from_txt_url(url)
        if pdf_url:
            title_hint = url.split("CELEX:")[-1] + " (PDF)"
            scrape_pdf_and_save("EU", pdf_url, title_hint=title_hint)


# ---------------------------------------------------------------------------
# 5. 🇺🇸 FMVSS (49 CFR Part 571) via ecfr.io
# ---------------------------------------------------------------------------

USA_INDEX_URL = "https://ecfr.io/Title-49/Part-571"
USA_SECTION_PREFIX = "/Title-49/Section-571."

USA_URLS = [
    "https://ecfr.io/Title-49/Part-565",  # VIN
    "https://ecfr.io/Title-49/Part-566",  # Manufacturer identification
    "https://ecfr.io/Title-49/Part-567",  # Certification
    "https://ecfr.io/Title-49/Part-568",  # Vehicles built in two or more stages
]


def scrape_usa_fmvss():
    """
    1) Récupère la page index Part 571 sur ecfr.io
    2) Trouve tous les liens /Title-49/Section-571.xxx
    3) Télécharge chaque section et l'enregistre dans USA.db
       + éventuels PDFs liés aux pages.
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
# 6. 🇮🇳 AIS – Ministry of Road Transport & Highways (morth.nic.in)
# ---------------------------------------------------------------------------

INDIA_AIS_BASE = "https://morth.nic.in/ais"


def parse_ais_table(soup: BeautifulSoup):
    """
    Dans la page AIS, trouve la table "Automotive Industry Standards (AIS)"
    et enregistre chaque ligne (AIS code + Subject + PDF) dans India.db,
    en essayant aussi de récupérer le texte du PDF.
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

        # Métadonnées de base
        content_lines = [
            f"AIS code: {ais_code}",
            f"Subject: {subject}",
            f"Status: {status}",
            f"Date: {date_str}",
            f"PDF: {pdf_url}",
        ]

        # >>> Essayer de récupérer le texte du PDF associé
        if pdf_tag and pdf_url:
            if not pdf_already_saved("India", pdf_url):
                pdf_bytes = fetch_pdf_bytes(pdf_url)
                if pdf_bytes:
                    pdf_text = extract_pdf_text(pdf_bytes)
                    if pdf_text:
                        content_lines.append("\n--- PDF TEXT ---\n")
                        content_lines.append(pdf_text)
                        print(f"[OK] Texte PDF AIS récupéré pour {ais_code}")
                    else:
                        print(f"[WARN] Impossible d'extraire le texte PDF pour {ais_code}")
                else:
                    print(f"[WARN] Impossible de télécharger le PDF pour {ais_code}")
            else:
                print(f"[INFO] PDF déjà présent dans India.db pour {ais_code}")

        content = "\n".join(content_lines)
        save_regulation("India", title, pdf_url, content)
        count += 1

    print(f"[OK] {count} normes AIS ajoutées / mises à jour sur cette page.")


# ---------------------------------------------------------------------------
# 🇫🇷 France – quelques textes clés sur sites officiels + PDF liés
# ---------------------------------------------------------------------------

FRANCE_URLS = [
    # Homologation / réception des véhicules
    "https://www.ecologie.gouv.fr/politiques-publiques/homologation-vehicules",

    # Politique véhicules électriques
    "https://www.ecologie.gouv.fr/politiques-publiques/developper-vehicules-electriques",

    # Infrastructures de recharge
    "https://www.ecologie.gouv.fr/politiques-publiques/developpement-nouveaux-equipements-reseaux-recharges-vehicules-electriques",

    # Rétrofit électrique
    "https://www.ecologie.gouv.fr/politiques-publiques/savoir-retrofit-electrique",

    # Dossier : financer son passage à l’électrique
    "https://www.ecologie.gouv.fr/dossiers/savoir-passer-lelectrique/financer-son-passage-lelectrique",
]


def scrape_france():
    print("\n================= 🇫🇷 Scraping France (liste fixe) =================")
    for url in FRANCE_URLS:
        scrape_text_page("France", url)


# ---------------------------------------------------------------------------
# 🇮🇳 India – pages ministérielles générales (en plus des AIS)
# ---------------------------------------------------------------------------

INDIA_URLS = [
    # Page ministère qui liste Motor Vehicles Act + CMVR
    "https://parivahan.gov.in/parivahan/en/content/act-rules-and-policies",

    # Fiche officielle CMVR 1989 (MORTH)
    "https://morth.nic.in/en/central-motor-vehicles-rules-1989",
]


def scrape_india_ais():
    """
    Crawl toutes les pages AIS (pagination ?page=N), et enregistre
    chaque entrée dans India.db, avec texte PDF quand possible.
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
# 🇬🇧 UK – quelques textes clés sur sites officiels + PDF liés
# ---------------------------------------------------------------------------

UK_URLS = [
    # Vue d'ensemble de la procédure d'approval (import, véhicule construit, modifié, etc.)
    "https://www.gov.uk/vehicle-approval/overview",

    # Page centrale VCA sur la type-approval (GB, UK(NI), UNECE...)
    "https://www.vehicle-certification-agency.gov.uk/vehicle-type-approval/",

    # Explications détaillées : "What is Vehicle Type Approval?"
    "https://www.vehicle-certification-agency.gov.uk/vehicle-type-approval/what-is-vehicle-type-approval/",

    # Provisional GB Type Approval scheme (post-Brexit)
    "https://www.vehicle-certification-agency.gov.uk/vehicle-type-approval/provisional-gb-type-approval-scheme/",
]


def scrape_uk():
    print("\n================= 🇬🇧 Scraping UK (liste fixe) =================")
    for url in UK_URLS:
        scrape_text_page("UK", url)


# ---------------------------------------------------------------------------
# 🇨🇳 & 🇯🇵 – URLs à compléter (scrape simple + PDF liés)
# ---------------------------------------------------------------------------

CHINA_URLS = [
    # Index général des standards "Emission Standard for Mobile-source Pollutants"
    "https://english.mee.gov.cn/Resources/standards/Air_Environment/emission_mobile/",

    # Emissions light-duty vehicles (GB 18352.3-2005 – Euro III/IV like)
    "https://english.mee.gov.cn/Resources/standards/Air_Environment/emission_mobile/200710/t20071024_111848.shtml",

    # China V – Limits and methods for emissions from light-duty vehicles (GB 18352.5-2013)
    "https://english.mee.gov.cn/Resources/standards/Air_Environment/emission_mobile/201605/t20160511_337517.shtml",

    # Hybrid light-duty vehicles (GB 19755-2016)
    "https://english.mee.gov.cn/Resources/standards/Air_Environment/emission_mobile/201609/t20160902_363506.shtml",

    # Bruit – tri-wheel & low-speed vehicle (référence à GB 7258)
    "https://english.mee.gov.cn/Resources/standards/Noise/Method_standard3/200907/t20090716_156194.shtml",
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
# Main
# ---------------------------------------------------------------------------

def main():
    init_db()

    scrape_eu()
    scrape_usa_fmvss()
    scrape_india_ais()
    scrape_china()
    scrape_japan()
    scrape_france()
    scrape_uk()

    # + éventuellement les pages India générales
    for url in INDIA_URLS:
        scrape_text_page("India", url)

    print("\n✅ Scraping terminé. Tu peux maintenant relancer search_all.py pour tester.")


if __name__ == "__main__":
    main()
