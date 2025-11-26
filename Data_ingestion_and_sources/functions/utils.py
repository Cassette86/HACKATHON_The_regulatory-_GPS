# utils.py
import sqlite3
from pathlib import Path
from typing import Iterable, Any

BASE_DIR = Path(__file__).resolve().parent

DB_PATHS = {
    "EU": BASE_DIR / "EU.db",
    "USA": BASE_DIR / "USA.db",
    "India": BASE_DIR / "India.db",
    "China": BASE_DIR / "China.db",
    "Japan": BASE_DIR / "Japan.db",
}


def get_connection(region: str) -> sqlite3.Connection:
    """Ouvre une connexion vers la DB d'une région."""
    if region not in DB_PATHS:
        raise ValueError(f"Région inconnue : {region} (choix: {list(DB_PATHS)})")
    return sqlite3.connect(DB_PATHS[region])


def get_all_records(region: str, limit: int | None = None) -> list[tuple[Any, ...]]:
    """Retourne toutes les lignes (ou les 'limit' premières) pour une région."""
    conn = get_connection(region)
    cur = conn.cursor()
    query = "SELECT id, title, source_url, pdf_url, retrieved_at FROM regulations ORDER BY id"
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    cur.execute(query)
    rows = cur.fetchall()
    conn.close()
    return rows


def get_record_by_id(region: str, record_id: int) -> tuple[Any, ...] | None:
    """Retourne un enregistrement complet par ID."""
    conn = get_connection(region)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, title, source_url, pdf_url, content, retrieved_at "
        "FROM regulations WHERE id = ?",
        (record_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def search_by_keyword(region: str, keyword: str, limit: int | None = 50) -> list[tuple[Any, ...]]:
    """
    Recherche simple par mot-clé dans le titre + le contenu.
    """
    conn = get_connection(region)
    cur = conn.cursor()
    like = f"%{keyword}%"
    query = """
        SELECT id, title, source_url, substr(content, 1, 300) AS snippet, retrieved_at
        FROM regulations
        WHERE (title LIKE ? OR content LIKE ?)
        ORDER BY id
    """
    if limit is not None:
        query += f" LIMIT {int(limit)}"

    cur.execute(query, (like, like))
    rows = cur.fetchall()
    conn.close()
    return rows


def count_records(region: str) -> int:
    """Compte le nombre de lignes pour une région."""
    conn = get_connection(region)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM regulations")
    n = cur.fetchone()[0]
    conn.close()
    return n


def list_available_regions() -> Iterable[str]:
    """Renvoie la liste des régions pour lesquelles la DB existe sur disque."""
    return [r for r, p in DB_PATHS.items() if p.exists()]
