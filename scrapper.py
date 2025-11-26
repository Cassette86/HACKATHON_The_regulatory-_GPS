# scraper.py
import sqlite3
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin

# ─────────────────────────────────────────────
# Configuration générale
# ─────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent

DB_PATHS = {
    "EU": BASE_DIR / "EU.db",
    "USA": BASE_DIR / "USA.db",
    "India": BASE_DIR / "India.db",
    "China": BASE_DIR / "China.db",
    "Japan": BASE_DIR / "Japan.db",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; regulations-bot/1.0; +https://example.com)"
}

# ─────────────────────────────────────────────
# Base de données
# ─────────────────────────────────────────────

def init_db(db_path: Path) -> None:
    """Crée la table regulations si elle n'existe pas."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS regulations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            source_url TEXT,
            pdf_url TEXT,
            content TEXT,
            retrieved_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def save_record(region: str, title: str, source_url: str,
                pdf_url: str | None, content: str | None) -> None:
    """Insère un enregistrement dans la DB du pays demandé."""
    db_path = DB_PATHS[region]
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Option simple : on évite les doublons basés sur (title, source_url)
    c.execute(
        """
        SELECT id FROM regulations
        WHERE title = ? AND source_url = ?
        """,
        (title, source_url),
    )
    exists = c.fetchone()
    if exists:
        conn.close()
        return

    c.execute(
        """
        INSERT INTO regulations (title, source_url, pdf_url, content, retrieved_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            title,
            source_url,
            pdf_url,
            content,
            datetime.utcnow().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# Helpers de scraping
# ─────────────────────────────────────────────

def fetch_html(url: str) -> BeautifulSoup | None:
    """Télécharge une page HTML et renvoie un BeautifulSoup, ou None en cas d'erreur."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"[ERREUR] Impossible de récupérer {url} : {e}")
        return None


def extract_text_from_elements(elements, max_chars: int = 4000) -> str:
    """Concatène le texte de plusieurs éléments, tronqué à max_chars."""
    if not elements:
        return ""
    texts = []
    total = 0
    for el in elements:
        t = " ".join(el.stripped_strings)
        if not t:
            continue
        if total + len(t) > max_chars:
            t = t[: max_chars - total]
            texts.append(t)
            break
        texts.append(t)
        total += len(t)
        if total >= max_chars:
            break
    return "\n\n".join(texts)


def scrape_simple_pages(region: str, urls: list[str],
                        title_selector: str | None = None,
                        content_selector: str | None = None) -> None:
    """
    Scraping générique :
    - récupère chaque URL
    - extrait un titre + un contenu texte
    - enregistre dans la DB du region.
    """
    for url in urls:
        print(f"[{region}] Scraping {url}")
        soup = fetch_html(url)
        if soup is None:
            continue

        # Titre
        title = None
        if title_selector:
            title_el = soup.select_one(title_selector)
            if title_el:
                title = title_el.get_text(strip=True)
        if not title:
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
            else:
                # fallback : premier h1 ou h2
                h = soup.find(["h1", "h2"])
                title = h.get_text(strip=True) if h else url

        # Contenu
        content = ""
        if content_selector:
            container = soup.select_one(content_selector)
            if container:
                content = extract_text_from_elements([container])
        else:
            # Par défaut : on prend les premiers <p>
            paragraphs = soup.find_all("p")
            content = extract_text_from_elements(paragraphs)

        save_record(region, title, url, None, content or None)


# ─────────────────────────────────────────────
# Scraping par région
# (les URLs sont *réelles*, mais tu peux les changer / compléter)
# ─────────────────────────────────────────────

def scrape_eu() -> None:
    """
    Exemple : quelques actes EUR-Lex en lien avec les véhicules.
    Tu peux compléter la liste avec d'autres règlements qui t'intéressent.
    """
    urls = [
        # Exemple réel : règlement d’exécution avec dataset véhicules
        "https://eur-lex.europa.eu/eli/reg_impl/2019/1129/oj/eng",
        # Tu peux ajouter ici d'autres actes:
        # "https://eur-lex.europa.eu/eli/reg/2019/2144/oj",
        # "https://eur-lex.europa.eu/eli/reg/2018/858/oj",
    ]
    # Sur EUR-Lex, le titre principal est souvent dans #titleText ou .title
    scrape_simple_pages(
        region="EU",
        urls=urls,
        title_selector="#titleText, .title",
        content_selector="div.content, #PPWrap, .OJbox",
    )


def scrape_usa() -> None:
    """
    Exemple : pages NHTSA et FMVSS.
    """
    urls = [
        # Page NHTSA "Laws & Regulations"
        "https://www.nhtsa.gov/laws-regulations",
        # Exemple : documentation sur FMVSS pour véhicules automatisés
        "https://www.nhtsa.gov/document/nhtsas-fmvss-considerations-vehicles-automated-driving-systems",
    ]
    scrape_simple_pages(
        region="USA",
        urls=urls,
        title_selector="h1, .page-title",
        content_selector="main, #main-content, .region-content",
    )


def scrape_india() -> None:
    """
    Scraping de la liste AIS sur le site du Ministry of Road Transport & Highways.
    On récupère les lignes du tableau AIS : code + sujet + lien PDF.
    """
    # Version "print" plus simple à parser
    url = "https://morth.nic.in/print/ais"
    print(f"[India] Scraping tableau AIS : {url}")
    soup = fetch_html(url)
    if soup is None:
        return

    table = soup.find("table")
    if not table:
        print("[India] Aucune table trouvée sur la page AIS.")
        return

    rows = table.find_all("tr")
    # On saute la ligne d'en-tête
    for row in rows[1:]:
        cols = row.find_all("td")
        if len(cols) < 3:
            continue

        # Structure observée : S. No. | AIS Code | Subject | Status | Download | Date
        s_no = cols[0].get_text(strip=True)
        ais_code = cols[1].get_text(strip=True)
        subject = cols[2].get_text(strip=True)

        download_link = row.find("a")
        pdf_url = None
        if download_link and download_link.get("href"):
            pdf_url = urljoin(url, download_link["href"])

        title = f"{ais_code} - {subject} (AIS India)"
        content = f"S. No.: {s_no}\nAIS Code: {ais_code}\nSubject: {subject}"
        save_record("India", title, url, pdf_url, content)


def scrape_china() -> None:
    """
    Exemple : standards environnementaux liés aux véhicules
    sur le site du Ministère de l'Écologie et de l'Environnement (MEE).
    """
    urls = [
        # Limites et mesure du bruit des véhicules tri-roues / basse vitesse
        "https://english.mee.gov.cn/Resources/standards/Noise/Method_standard3/200907/t20090716_156194.shtml",
        # Emissions polluants petites machines mobiles
        "https://english.mee.gov.cn/standards_reports/standards/Air_Environment/emission_mobile/201103/t20110304_201447.htm",
        # Emissions polluants moteurs essence véhicules lourds
        "https://english.mee.gov.cn/Resources/standards/Air_Environment/emission_mobile/200810/t20081031_130729.shtml",
    ]
    scrape_simple_pages(
        region="China",
        urls=urls,
        title_selector="h1, .title",
        content_selector="div#Content, .content, #Zoom",
    )


def scrape_japan() -> None:
    """
    Exemple : lois / notifications liées aux véhicules (MLIT, Road Vehicles Law).
    """
    urls = [
        # Présentation de la Road Vehicles Law
        "https://www8.cao.go.jp/kisei-kaikaku/oto/otodb/english/houseido/hou/lh_06050.html",
        # Notification concernant la révision des Safety Regulations (bruit)
        "https://www.mlit.go.jp/english/mot_news/mot_news_970808.html",
        # Road Traffic Act (très complet, mais bon exemple)
        "https://www.japaneselawtranslation.go.jp/en/laws/view/2962/en",
    ]
    scrape_simple_pages(
        region="Japan",
        urls=urls,
        title_selector="h1, h2, .title",
        content_selector="div#main, #contents, .content, article",
    )


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def init_all_dbs() -> None:
    """Crée toutes les bases si besoin."""
    for region, db_path in DB_PATHS.items():
        print(f"[INIT] Création / vérification de la DB pour {region} : {db_path}")
        init_db(db_path)


def scrape_all() -> None:
    """Lance le scraping pour tous les pays."""
    init_all_dbs()
    print("\n=== Scraping EU ===")
    scrape_eu()
    print("\n=== Scraping USA ===")
    scrape_usa()
    print("\n=== Scraping India ===")
    scrape_india()
    print("\n=== Scraping China ===")
    scrape_china()
    print("\n=== Scraping Japan ===")
    scrape_japan()
    print("\n✅ Terminé. Les bases sont remplies dans le dossier du script.")


if __name__ == "__main__":
    scrape_all()
