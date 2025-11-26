import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from typing import List, Dict, Tuple, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pdfminer.high_level import extract_text as pdf_extract_text

# Spécifique EUR-Lex (paquet eurlex-parser)
from eurlex import get_data_by_celex_id


# ===========================================
# CONFIG GLOBALE
# ===========================================

DB_PATH = "regulations.db"

REQUEST_DELAY = 1.0  # secondes entre requêtes pour le crawler générique
TIMEOUT = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36"
    ),
    "Accept-Language": "en;q=0.9,fr;q=0.8",
}

# ------------------------------
#  EU – CELEX (EUR-Lex)
# ------------------------------
# ⚠️ Liste à enrichir avec tous les CELEX que tu veux couvrir.
# Ici quelques exemples très EV / sécurité / type-approval.
EU_CELEX_IDS = [
    "32018R0858",  # Type-approval & market surveillance of motor vehicles (règlement cadre)
    "32019R2144",  # General Safety Regulation (ADAS, protection VRU, etc.)
    # Exemple : émissions CO2 flotte véhicules légers (utile EV/ICE mix)
    "32019R0631",
    # Ajoute ici d'autres règlements/directions EV ou sécurité que tu connais
]

# ------------------------------
#  CRAWLER GÉNÉRIQUE – CONFIG PAR PAYS / SOURCE
# ------------------------------


@dataclass
class CrawlerConfig:
    name: str
    jurisdiction: str
    source: str
    start_urls: List[str]
    allowed_domains: List[str]
    max_depth: int = 2
    max_pages: int = 100
    extra_pdf_urls: List[str] = field(default_factory=list)


# 🇺🇸 USA – NHTSA / FMVSS / docs EV (exemples, à enrichir)
USA_CONFIG = CrawlerConfig(
    name="USA_NHTSA",
    jurisdiction="US",
    source="NHTSA",
    start_urls=[
        # Page lois & FMVSS
        "https://www.nhtsa.gov/laws-regulations",
        # Exemple d’analyse FMVSS liée aux systèmes automatisés (souvent EV / ADAS)
        "https://www.nhtsa.gov/document/fmvss-considerations-vehicles-automated-driving-systems",
    ],
    allowed_domains=["www.nhtsa.gov", "nhtsa.gov"],
    max_depth=2,
    max_pages=80,
    extra_pdf_urls=[
        # Exemple de PDF direct depuis la bibliothèque ROSA (lien stable)
        "https://rosap.ntl.bts.gov/view/dot/54287/dot_54287_DS1.pdf",
    ],
)

# 🇪🇺 UNECE – Règlements véhicules (notamment EV / HFCV / batteries)
UNECE_CONFIG = CrawlerConfig(
    name="UNECE_VehicleRegs",
    jurisdiction="UNECE",
    source="UNECE",
    start_urls=[
        # Page globale WP.29 véhicules
        "https://unece.org/transport/vehicle-regulations",
        # Législation japonaise HFCV – beaucoup de PDFs EV/H2
        "https://unece.org/japanese-legislation-hfcv",
    ],
    allowed_domains=["unece.org"],
    max_depth=2,
    max_pages=80,
)

# 🇯🇵 Japon – MLIT (sécurité véhicules)
JAPAN_CONFIG = CrawlerConfig(
    name="Japan_MLIT",
    jurisdiction="JP",
    source="MLIT",
    start_urls=[
        "https://www.mlit.go.jp/english/inspect/car09e.html",  # Inspection & Safety Regulations
    ],
    allowed_domains=["www.mlit.go.jp", "mlit.go.jp"],
    max_depth=1,
    max_pages=30,
)

# 🇫🇷 France – pages publiques homologation / VE (à adapter)
FRANCE_CONFIG = CrawlerConfig(
    name="France_Misc",
    jurisdiction="FR",
    source="FR_GOV",
    start_urls=[
        # Homologation & immatriculation, import de véhicules
        "https://www.service-public.fr/particuliers/vosdroits/F20992",
        "https://www.service-public.fr/particuliers/vosdroits/F12097",
        # DREAL Bretagne – homologation véhicules (contenu très riche FAQ)
        "https://www.bretagne.developpement-durable.gouv.fr/refonte-des-pages-internet-consacrees-a-l-a5305.html",
    ],
    allowed_domains=[
        "www.service-public.fr",
        "service-public.fr",
        "www.bretagne.developpement-durable.gouv.fr",
        "bretagne.developpement-durable.gouv.fr",
    ],
    max_depth=1,
    max_pages=50,
)

# 🇬🇧 UK – Legislation.gov.uk (on reste simple / ciblé)
UK_CONFIG = CrawlerConfig(
    name="UK_Legislation",
    jurisdiction="UK",
    source="LEG_GOV_UK",
    start_urls=[
        # Portail API / documentation (souvent liens vers XML/HTML des textes)
        "https://www.legislation.gov.uk/",
    ],
    allowed_domains=["www.legislation.gov.uk", "legislation.gov.uk"],
    max_depth=1,
    max_pages=50,
)

# 🇮🇳 Inde – (exemple minimal : pages généralistes à enrichir avec AIS/AIS-standards)
INDIA_CONFIG = CrawlerConfig(
    name="India_Generic",
    jurisdiction="IN",
    source="MORTH_GENERIC",
    start_urls=[
        "https://morth.nic.in/",
    ],
    allowed_domains=["morth.nic.in", "www.morth.nic.in"],
    max_depth=1,
    max_pages=40,
)

# 🇨🇳 Chine – (exemple minimal, à adapter selon les sites ciblés : MIIT, etc.)
CHINA_CONFIG = CrawlerConfig(
    name="China_Generic",
    jurisdiction="CN",
    source="CN_GENERIC",
    start_urls=[
        "https://www.miit.gov.cn",  # Page d’accueil MIIT
    ],
    allowed_domains=["www.miit.gov.cn", "miit.gov.cn"],
    max_depth=1,
    max_pages=40,
)

GENERIC_CONFIGS = [
    USA_CONFIG,
    UNECE_CONFIG,
    JAPAN_CONFIG,
    FRANCE_CONFIG,
    UK_CONFIG,
    INDIA_CONFIG,
    CHINA_CONFIG,
]


# ===========================================
# BASE DE DONNÉES
# ===========================================

def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            jurisdiction TEXT,
            source       TEXT,
            celex        TEXT,
            law_id       TEXT,
            title        TEXT,
            text         TEXT,
            raw_json     TEXT,
            is_pdf       INTEGER DEFAULT 0,
            url          TEXT,
            content_type TEXT,
            status_code  INTEGER,
            fetched_at   TEXT,
            UNIQUE (jurisdiction, url)
        )
        """
    )
    conn.commit()
    return conn


def save_document(
    conn: sqlite3.Connection,
    jurisdiction: str,
    source: str,
    title: str,
    text: str,
    is_pdf: bool,
    url: Optional[str],
    status_code: Optional[int],
    content_type: Optional[str],
    celex: Optional[str] = None,
    law_id: Optional[str] = None,
    raw_json: Optional[str] = None,
):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO documents (
            jurisdiction, source, celex, law_id,
            title, text, raw_json,
            is_pdf, url, content_type, status_code, fetched_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            jurisdiction,
            source,
            celex,
            law_id,
            title,
            text,
            raw_json,
            1 if is_pdf else 0,
            url,
            content_type,
            status_code,
            datetime.utcnow().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


# ===========================================
# HELPERS HTTP / PARSING
# ===========================================

def is_pdf_url(url: str) -> bool:
    return url.lower().endswith(".pdf")


def fetch_url(url: str) -> Tuple[Optional[str], Optional[bytes], Optional[int], Optional[str]]:
    """
    Retourne (html_text, pdf_bytes, status_code, content_type).
    - html_text : str ou None
    - pdf_bytes : bytes ou None
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as e:
        print(f"[HTTP ERROR] {url} -> {e}")
        return None, None, None, None

    status = resp.status_code
    ctype = (resp.headers.get("Content-Type") or "").lower()

    print(f"[HTTP] {status} ({ctype}) -> {url}")

    # On accepte 2xx comme "OK" (ex : 202, 204… même si 204=vide)
    if not (200 <= status < 300):
        return None, None, status, ctype

    # PDF ?
    if "application/pdf" in ctype or is_pdf_url(url):
        return None, resp.content, status, ctype

    # HTML / texte
    resp.encoding = resp.encoding or "utf-8"
    html = resp.text or ""
    if not html.strip():
        print("    [DEBUG] Réponse (quasi) vide malgré 2xx")
    return html, None, status, ctype


def extract_html_text(html: str) -> Tuple[Tuple[str, str], List[str]]:
    """
    Retourne ((title, text), links)
    text = gros bloc texte pour RAG
    links = hrefs trouvés pour le crawler
    """
    soup = BeautifulSoup(html, "lxml")

    # Supprimer les éléments inutiles
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # Texte brut
    text = soup.get_text(separator="\n")
    # Nettoyage léger
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    text_clean = "\n".join(lines)

    links: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href and not href.startswith("javascript:"):
            links.append(href)

    return (title, text_clean), links


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """
    Utilise pdfminer pour extraire le texte.
    """
    try:
        b = BytesIO(pdf_bytes)
        txt = pdf_extract_text(b)
        if not txt:
            return ""
        # Petit nettoyage
        lines = [ln.rstrip() for ln in txt.splitlines()]
        return "\n".join(lines)
    except Exception as e:
        print(f"    [PDF ERROR] extraction impossible -> {e}")
        return ""


def normalize_url(base_url: str, href: str) -> Optional[str]:
    href = href.strip()
    if not href:
        return None
    if href.startswith("#"):
        return None
    # URL absolue ou relative
    return urljoin(base_url, href)


def should_follow(url: str, allowed_domains: List[str]) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if not parsed.scheme.startswith("http"):
        return False
    domain = parsed.netloc.lower()
    for d in allowed_domains:
        if domain.endswith(d.lower()):
            return True
    return False


# ===========================================
# 1) INGEST EUR-LEX (EURLEX-PARSER, PAR CELEX)
# ===========================================

def flatten_eurlex_data(data: Dict) -> Tuple[str, str]:
    """
    Transforme la structure riche de eurlex-parser
    (title, preamble, articles, annexes, final_part, ...)
    en un gros texte unique exploitable (RAG).
    """
    parts: List[str] = []

    title = data.get("title") or ""
    if title:
        parts.append(title)

    # Préambule
    preamble = (data.get("preamble") or {}).get("text")
    if preamble:
        parts.append("\n\nPREAMBLE\n" + preamble)

    # Articles
    for art in data.get("articles") or []:
        art_id = art.get("id") or ""
        art_title = art.get("title") or ""
        art_text = art.get("text") or ""
        block: List[str] = []
        header = " ".join([x for x in (art_id, art_title) if x]).strip()
        if header:
            block.append(header)
        if art_text:
            block.append(art_text)
        if block:
            parts.append("\n\n" + "\n".join(block))

    # Partie finale
    final_part = data.get("final_part")
    if final_part:
        parts.append("\n\nFINAL PART\n" + (final_part or ""))

    # Annexes
    for ann in data.get("annexes") or []:
        ann_id = ann.get("id") or ""
        ann_title = ann.get("title") or ""
        ann_text = ann.get("text") or ""
        ann_table = ann.get("table") or ""
        block = []
        header = f"ANNEX {ann_id} - {ann_title}".strip(" -")
        if header:
            block.append(header)
        if ann_text:
            block.append(ann_text)
        if ann_table:
            block.append("\nTABLE:\n" + ann_table)
        if block:
            parts.append("\n\n" + "\n".join(block))

    full_text = "\n".join(p for p in parts if p and p.strip())
    return title, full_text


def ingest_eu_eurlex(conn: sqlite3.Connection, celex_ids: List[str]):
    print("\n==============================")
    print("EUR-LEX – INGEST PAR CELEX")
    print("==============================\n")

    for celex in celex_ids:
        print(f"[EURLEX] CELEX {celex}")
        try:
            data = get_data_by_celex_id(celex)  # fourni par eurlex-parser
        except Exception as e:
            print(f"  [ERROR] get_data_by_celex_id({celex}) -> {e}")
            continue

        if not data:
            print(f"  [WARN] Aucun data pour {celex}")
            continue

        title, text = flatten_eurlex_data(data)
        if not text:
            print(f"  [WARN] Texte vide pour {celex}")
            continue

        import json

        raw_json = json.dumps(data, ensure_ascii=False)
        url = f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"

        save_document(
            conn=conn,
            jurisdiction="EU",
            source="EURLEX",
            title=title or celex,
            text=text,
            is_pdf=False,
            url=url,
            status_code=None,
            content_type="text/html;parsed-via-eurlex-parser",
            celex=celex,
            law_id=celex,
            raw_json=raw_json,
        )
        print(f"  [OK] {celex} – {len(text)} caractères stockés.")


# ===========================================
# 2) CRAWLER GENERIQUE HTML/PDF
# ===========================================

def crawl_generic(conn: sqlite3.Connection, cfg: CrawlerConfig):
    print("\n==============================")
    print(f"CRAWLER GENERIQUE – {cfg.name}")
    print("==============================")

    visited: set[str] = set()
    queue: deque[Tuple[str, int]] = deque()
    for u in cfg.start_urls:
        queue.append((u, 0))

    pages_saved = 0

    # 2.1 – PDFs explicites (URLs directes)
    for pdf_url in cfg.extra_pdf_urls:
        if pdf_url in visited:
            continue
        visited.add(pdf_url)
        print(f"[PDF-ONLY] {pdf_url}")
        html_text, pdf_bytes, status, ctype = fetch_url(pdf_url)
        if not pdf_bytes:
            print("    [WARN] Impossible de récupérer le PDF")
            continue
        text = extract_pdf_text(pdf_bytes)
        if not text:
            print("    [WARN] PDF sans texte lisible")
            continue
        title = pdf_url.rsplit("/", 1)[-1]
        save_document(
            conn,
            jurisdiction=cfg.jurisdiction,
            source=cfg.source,
            title=title,
            text=text,
            is_pdf=True,
            url=pdf_url,
            status_code=status,
            content_type=ctype,
        )
        pages_saved += 1
        print(f"    [OK] PDF stocké ({len(text)} caractères).")

    # 2.2 – Crawl BFS HTML/PDF
    while queue and pages_saved < cfg.max_pages:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        print(f"\n[CRAWL] depth={depth} {url}")
        html_text, pdf_bytes, status, ctype = fetch_url(url)

        if status is None:
            continue

        # Cas PDF
        if pdf_bytes is not None:
            text = extract_pdf_text(pdf_bytes)
            if not text:
                print("    [WARN] PDF sans texte lisible.")
            else:
                title = url.rsplit("/", 1)[-1]
                save_document(
                    conn,
                    jurisdiction=cfg.jurisdiction,
                    source=cfg.source,
                    title=title,
                    text=text,
                    is_pdf=True,
                    url=url,
                    status_code=status,
                    content_type=ctype,
                )
                pages_saved += 1
                print(f"    [OK] PDF enregistré ({len(text)} caractères).")
            print(f"    [STATS] pages enregistrées = {pages_saved}")
            time.sleep(REQUEST_DELAY)
            continue

        # Cas HTML
        if not html_text:
            print("    [INFO] Pas de HTML renvoyé.")
            time.sleep(REQUEST_DELAY)
            continue

        (title, content), links = extract_html_text(html_text)
        if not content:
            print("    [INFO] Page sans contenu exploitable.")
        else:
            save_document(
                conn,
                jurisdiction=cfg.jurisdiction,
                source=cfg.source,
                title=title or url,
                text=content,
                is_pdf=False,
                url=url,
                status_code=status,
                content_type=ctype,
            )
            pages_saved += 1
            print(f"    [OK] HTML enregistré ({len(content)} caractères).")

        # Ajout des liens au crawl si on n’a pas dépassé la profondeur max
        if depth < cfg.max_depth:
            for href in links:
                new_url = normalize_url(url, href)
                if not new_url:
                    continue
                if not should_follow(new_url, cfg.allowed_domains):
                    continue
                if new_url not in visited:
                    queue.append((new_url, depth + 1))

        print(f"    [STATS] pages enregistrées = {pages_saved}")
        time.sleep(REQUEST_DELAY)

    print(f"\n[FIN] {cfg.name} – Documents enregistrés : {pages_saved}")


# ===========================================
# MAIN
# ===========================================

def main():
    conn = init_db()

    # 1) EUR-Lex (EU)
    ingest_eu_eurlex(conn, EU_CELEX_IDS)

    # 2) Crawler générique pour les différents pays / organisations
    for cfg in GENERIC_CONFIGS:
        crawl_generic(conn, cfg)

    conn.close()
    print("\n[GLOBAL FIN] Tous les crawls terminés.")


if __name__ == "__main__":
    main()
