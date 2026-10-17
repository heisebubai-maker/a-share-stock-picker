import sqlite3
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(path, provider):
    with connect(path) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS bars (
          code TEXT, name TEXT NOT NULL, day TEXT, close REAL NOT NULL,
          amount REAL NOT NULL, is_st INTEGER NOT NULL, suspended INTEGER NOT NULL,
          source TEXT NOT NULL, PRIMARY KEY(source,code,day));
        CREATE TABLE IF NOT EXISTS reviews (
          source TEXT, day TEXT, strategy TEXT, summary TEXT NOT NULL,
          notes TEXT NOT NULL DEFAULT '', PRIMARY KEY(source,day,strategy));
        CREATE TABLE IF NOT EXISTS sync_state (
          source TEXT PRIMARY KEY, updated_at TEXT NOT NULL, start TEXT NOT NULL,
          end TEXT NOT NULL, codes TEXT NOT NULL, row_count INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS holdings (
          code TEXT PRIMARY KEY, cost REAL NOT NULL, quantity INTEGER NOT NULL,
          horizon TEXT NOT NULL, thesis TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS preferences (
          id INTEGER PRIMARY KEY CHECK(id=1), cash REAL NOT NULL DEFAULT 0,
          max_stock_pct REAL NOT NULL DEFAULT 20, max_total_pct REAL NOT NULL DEFAULT 70,
          max_loss_pct REAL NOT NULL DEFAULT 8, risk_pct REAL NOT NULL DEFAULT 1);
        INSERT OR IGNORE INTO preferences(id) VALUES(1);
        CREATE TABLE IF NOT EXISTS research_reports (
          source TEXT, day TEXT, payload TEXT NOT NULL, created_at TEXT NOT NULL,
          PRIMARY KEY(source,day));
        CREATE TABLE IF NOT EXISTS context (
          source TEXT, code TEXT, day TEXT, sector TEXT, pe REAL, pb REAL,
          PRIMARY KEY(source,code,day));
        CREATE TABLE IF NOT EXISTS benchmarks (
          source TEXT, code TEXT, day TEXT, close REAL NOT NULL,
          PRIMARY KEY(source,code,day));
        CREATE TABLE IF NOT EXISTS feed_status (
          source TEXT PRIMARY KEY,vendor TEXT NOT NULL,note TEXT NOT NULL);
        ''')
        db.executemany('INSERT OR IGNORE INTO bars VALUES (:code,:name,:day,:close,:amount,:is_st,:suspended,:source)',
                       [dict(row, source=provider.name) for row in provider.bars()])


def save_market(path, source, rows, codes, start, end, benchmarks=None, refresh_from=None,vendor=None,note=''):
    import json
    from datetime import datetime, timezone
    with connect(path) as db:
        # For an unchanged pool reuse validated older history, replacing the overlap atomically.
        if refresh_from:
            db.execute('DELETE FROM bars WHERE source=? AND (day>=? OR day<? OR day>?)',
                       (source,refresh_from.isoformat(),start.isoformat(),end.isoformat()))
        else:
            db.execute('DELETE FROM bars WHERE source=?', (source,))
        db.executemany('INSERT INTO bars VALUES (:code,:name,:day,:close,:amount,:is_st,:suspended,:source)',
                       [dict(row, source=source) for row in rows])
        if refresh_from:
            db.execute('DELETE FROM context WHERE source=? AND (day>=? OR day<? OR day>?)',
                       (source,refresh_from.isoformat(),start.isoformat(),end.isoformat()))
        else:
            db.execute('DELETE FROM context WHERE source=?', (source,))
        db.executemany('INSERT INTO context VALUES (?,?,?,?,?,?)',
                       [(source,r['code'],r['day'],r.get('sector'),r.get('pe'),r.get('pb')) for r in rows])
        if benchmarks is not None:
            if refresh_from:
                db.execute('DELETE FROM benchmarks WHERE source=? AND (day>=? OR day<? OR day>?)',
                           (source,refresh_from.isoformat(),start.isoformat(),end.isoformat()))
            else:
                db.execute('DELETE FROM benchmarks WHERE source=?', (source,))
            db.executemany('INSERT INTO benchmarks VALUES (?,?,?,?)',
                           [(source,r['code'],r['day'],r['close']) for r in benchmarks])
        total=db.execute('SELECT COUNT(*) FROM bars WHERE source=?',(source,)).fetchone()[0]
        db.execute('INSERT OR REPLACE INTO feed_status VALUES(?,?,?)',(source,vendor or source,note))
        db.execute('''INSERT OR REPLACE INTO sync_state VALUES (?,?,?,?,?,?)''',
                   (source, datetime.now(timezone.utc).isoformat(), start.isoformat(),
                    end.isoformat(), json.dumps(codes), total))
