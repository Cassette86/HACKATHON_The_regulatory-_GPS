# query_ev.py
import sqlite3
import glob
import os
from textwrap import shorten

# Mots-clés recherchés (insensible à la casse)
KEYWORDS = ["electric", "battery", "hybrid"]

DB_GLOB = "*.db"          # on parcourt tous les .db du dossier
TABLE_NAME = "documents"  # table utilisée par ton scrapper
# Colonnes minimales connues : id, title, url
TITLE_COL = "title"
URL_COL = "url"
CONTENT_COL = "content"   # on essaie de l'utiliser si elle existe


def detect_has_content_column(conn) -> bool:
    """
    Vérifie si la table 'documents' contient une colonne 'content'.
    Si ce n'est pas le cas, on ne cherchera les mots-clés que dans title/url.
    """
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({TABLE_NAME});")
    cols = [row[1].lower() for row in cur.fetchall()]
    return CONTENT_COL.lower() in cols


def build_where_clause(has_content: bool) -> str:
    clauses = []

    # Recherche dans le titre et l'URL (toujours possible)
    for kw in KEYWORDS:
        kw = kw.lower()
        clauses.append(f"LOWER({TITLE_COL}) LIKE '%{kw}%'")
        clauses.append(f"LOWER({URL_COL})   LIKE '%{kw}%'")

    # Si on a une colonne content, on l'ajoute aussi
    if has_content:
        for kw in KEYWORDS:
            kw = kw.lower()
            clauses.append(f"LOWER({CONTENT_COL}) LIKE '%{kw}%'")

    return " OR ".join(clauses)


def query_db(db_path: str):
    region = os.path.splitext(os.path.basename(db_path))[0]  # ex: EU.db -> EU
    print("=" * 80)
    print(f"[DB] {db_path} (region = {region})")
    print("=" * 80)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Vérifie présence colonne 'content'
    has_content = detect_has_content_column(conn)
    if has_content:
        print("[INFO] Colonne 'content' détectée → recherche dans title, url ET content\n")
    else:
        print("[INFO] Aucune colonne 'content' détectée → recherche uniquement dans title et url\n")

    where_clause = build_where_clause(has_content)

    # On limite un extrait pour ne pas inonder le terminal
    select_extract = (
        f"SUBSTR({CONTENT_COL}, 1, 400) AS extract"
        if has_content
        else "NULL AS extract"
    )

    sql = f"""
        SELECT
            id,
            {TITLE_COL} AS title,
            {URL_COL}   AS url,
            {select_extract}
        FROM {TABLE_NAME}
        WHERE {where_clause}
        ORDER BY id
        LIMIT 500;
    """

    try:
        cur.execute(sql)
    except sqlite3.OperationalError as e:
        print(f"[ERREUR SQL] {e}")
        print("Vérifie les noms de table/colonnes avec par ex. :")
        print(f'  sqlite3 "{db_path}" ".schema {TABLE_NAME}"')
        conn.close()
        return

    rows = cur.fetchall()
    print(f"[INFO] {len(rows)} lignes trouvées contenant {KEYWORDS}\n")

    for row in rows:
        id_ = row["id"]
        title = row["title"]
        url = row["url"]
        extract = row["extract"] or ""
        if extract:
            extract = shorten(
                extract.replace("\n", " ").replace("\r", " "),
                width=200,
                placeholder="..."
            )

        print(f"[{region}] id={id_} | {title}")
        print(f"  URL     : {url}")
        if extract:
            print(f"  Extrait : {extract}")
        print("-" * 80)

    conn.close()


def main():
    db_files = sorted(glob.glob(DB_GLOB))
    if not db_files:
        print("[INFO] Aucun fichier .db trouvé dans le dossier courant.")
        return

    print("[INFO] Bases trouvées :", ", ".join(db_files))
    print()

    for db in db_files:
        query_db(db)


if __name__ == "__main__":
    main()
