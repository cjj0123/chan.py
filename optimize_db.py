import sqlite3
import os

DB_PATH = "chan_trading.db"

def optimize_db():
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} not found.")
        return

    print(f"Connecting to {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    indices_to_drop = [
        # Redundant composite indices (already covered by PRIMARY KEY)
        "idx_kline_day_code_date",
        "idx_kline_30m_code_date",
        "idx_kline_5m_code_date",
        "idx_kline_1m_code_date",
        
        # Redundant desc date indices (rarely useful for our query patterns)
        "idx_kline_day_date_desc",
        "idx_kline_30m_date_desc",
        "idx_kline_5m_date_desc",
        "idx_kline_1m_date_desc"
    ]

    for index in indices_to_drop:
        try:
            print(f"Dropping index {index}...")
            cursor.execute(f"DROP INDEX IF EXISTS {index}")
        except Exception as e:
            print(f"Failed to drop {index}: {e}")

    conn.commit()

    print("Running VACUUM to reclaim space and optimize B-Trees... This may take a few seconds.")
    conn.execute("VACUUM")
    
    conn.close()
    print("Optimization complete!")

if __name__ == "__main__":
    optimize_db()
