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
        ''')
        db.executemany('INSERT OR IGNORE INTO bars VALUES (:code,:name,:day,:close,:amount,:is_st,:suspended,:source)',
                       [dict(row, source=provider.name) for row in provider.bars()])
