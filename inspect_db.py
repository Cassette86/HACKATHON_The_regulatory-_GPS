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

for region, db_path in DB_PATHS.items():
    print(f"\n=== {region} -> {db_path} ===")
    if not db_path.exists():
        print("  (fichier inexistant)")
        continue

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # nombre total de lignes
    c.execute("SELECT COUNT(*) FROM regulations")
    total = c.fetchone()[0]
    print(f"  Total lignes : {total}")

    # afficher les 3 premières
    c.execute("SELECT id, title, source_url FROM regulations LIMIT 3")
    rows = c.fetchall()
    for row in rows:
        print(f"  id={row[0]} | title={row[1]!r} | url={row[2]}")
    conn.close()
