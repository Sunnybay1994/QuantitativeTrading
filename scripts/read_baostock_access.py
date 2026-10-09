"""Read shared BaoStock state without initializing or changing the database."""
import json
import os
from pathlib import Path
import sqlite3


def main():
    root = (Path(os.environ.get('PROGRAMDATA', 'C:/ProgramData')) / 'QuantitativeTrading/baostock_access'
            if os.name == 'nt' else Path('/var/lib/quantitative-trading/baostock_access'))
    path = root / 'requests.sqlite'
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        blocked = db.execute('SELECT blocked FROM control WHERE id=1').fetchone()
        result = {
            'database': str(path),
            'blacklist_blocked': bool(blocked and blocked[0]),
            'requests_in_rolling_24h': db.execute(
                "SELECT COUNT(*) FROM requests WHERE at>CAST(strftime('%s','now') AS REAL)-86400").fetchone()[0],
            'sessions_initialized': 'sessions' in tables,
            'latest_sessions': db.execute('SELECT at,pid,event FROM sessions ORDER BY at DESC LIMIT 5').fetchall()
                if 'sessions' in tables else [],
        }
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
