import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DB_PATHS = {
    "EU": BASE_DIR / "EU.db",
    "USA": BASE_DIR / "USA.db",
    "India": BASE_DIR / "India.db",
    "China": BASE_DIR / "China.db",
    "Japan": BASE_DIR / "Japan.db",
}

def search_keyword(keyword: str) -> None:
    pattern = f"%{keyword}%"

    for region, db_path in DB_PATHS.items():
        if not db_path.exists():
            continue

        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        c.execute(
            """
            SELECT id, title, source_url, substr(content, 1, 200)
            FROM regulations
            WHERE title LIKE ? OR content LIKE ?
            LIMIT 20
            """,
            (pattern, pattern),
        )
        rows = c.fetchall()
        conn.close()

        if not rows:
            continue

        print(f"\n=== {region} – résultats pour '{keyword}' ===")
        for rid, title, url, snippet in rows:
            print(f"- [{region} #{rid}] {title}")
            print(f"  URL : {url}")
            if snippet:
                # on nettoie avant de l’utiliser dans la f-string
                snippet_clean = snippet.replace("\n", " ")[:180]
                print(f"  Extrait : {snippet_clean}...")
        print()

if __name__ == "__main__":
    kw = input("Mot-clé à chercher : ")
    search_keyword(kw)
