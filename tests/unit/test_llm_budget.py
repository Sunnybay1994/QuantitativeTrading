from quant.llm.budget import month_spend_usd, remaining_budget_usd


def test_missing_cache_is_zero(tmp_path):
    path = tmp_path / "missing.sqlite"
    assert month_spend_usd(path) == 0.0
    assert remaining_budget_usd(30, path) == 30.0


def test_month_spend_reads_attempts(tmp_path):
    import sqlite3
    from datetime import datetime, timezone

    path = tmp_path / "cache.sqlite"
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE attempts (
        id INTEGER PRIMARY KEY, created_at TEXT, state TEXT,
        reserved_usd REAL, charged_usd REAL)""")
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "INSERT INTO attempts(created_at,state,reserved_usd,charged_usd) VALUES (?,?,?,?)",
        (now, "ok", 0.0, 1.25),
    )
    db.commit()
    db.close()
    assert abs(month_spend_usd(path) - 1.25) < 1e-9
    assert remaining_budget_usd(30, path) == 28.75
