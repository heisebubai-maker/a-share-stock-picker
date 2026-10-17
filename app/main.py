import json
import os
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from .providers import get_provider
from .storage import connect, initialize, save_market
from .strategy import VERSION, evaluate
from .market import DEFAULT_CODES, DataError, china_today, download, normalize_codes

ROOT = Path(__file__).resolve().parent


class Note(BaseModel):
    notes: str = Field(max_length=5000)


class SyncRequest(BaseModel):
    codes: list[str] = Field(default_factory=lambda: list(DEFAULT_CODES), min_length=1, max_length=50)
    start: date = Field(default_factory=lambda: china_today() - timedelta(days=180))
    end: date = Field(default_factory=lambda: china_today() - timedelta(days=1))

    @model_validator(mode='after')
    def valid_range(self):
        self.codes = normalize_codes(self.codes)
        if not self.start <= self.end < china_today() or (self.end - self.start).days > 370:
            raise ValueError('范围最多370天，结束日期必须早于今天')
        return self


def create_app(db_path=None, source=None):
    path = db_path or os.environ.get("STOCK_DB", str(ROOT.parent / "data" / "stock.sqlite3"))
    provider = get_provider(source or os.environ.get("STOCK_SOURCE", "baostock"))
    simulated = provider.name == 'demo'
    sync_lock = Lock()

    @asynccontextmanager
    async def lifespan(app):
        initialize(path, provider)
        yield

    app = FastAPI(title="A股选股复盘 · 本地研究版", lifespan=lifespan)

    @app.middleware("http")
    async def local_writes(request: Request, call_next):
        # Prevent browser cross-origin writes to the local service.
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("origin") not in (None, str(request.base_url).rstrip("/")):
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "不允许跨站写入"}, status_code=403)
        return await call_next(request)

    def snapshot(day):
        with connect(path) as db:
            rows = [dict(r) for r in db.execute(
                'SELECT * FROM bars WHERE source=? AND day<=? ORDER BY code,day',
                (provider.name, day.isoformat()))]
        if not rows or max(r["day"] for r in rows) != day.isoformat():
            raise HTTPException(404, "该日期无数据，请选择已有样本日期")
        groups = {}
        for row in rows:
            groups.setdefault(row["code"], []).append(row)
        results = [evaluate(v) for v in groups.values() if v[-1]["day"] == day.isoformat()]
        ranked = sorted([r for r in results if r], key=lambda r: (-r["score"], r["code"]))
        available = sum(v[-1]['day'] == day.isoformat() for v in groups.values())
        return dict(day=day.isoformat(), source=provider.name, simulated=simulated,
                    adjustment='none', strategy=VERSION, universe=len(groups),
                    available=available, missing=len(groups)-available, eligible=len(ranked), items=ranked)

    @app.get("/api/health")
    def health():
        with connect(path) as db:
            db.execute('SELECT 1').fetchone()
        return dict(status="ok", source=provider.name, simulated=simulated)

    @app.get('/api/data-status')
    def data_status():
        with connect(path) as db:
            state = db.execute('SELECT * FROM sync_state WHERE source=?', (provider.name,)).fetchone()
            latest = db.execute('SELECT MAX(day) FROM bars WHERE source=?', (provider.name,)).fetchone()[0]
        return dict(source=provider.name, simulated=simulated, latest_day=latest,
                    age_days=(china_today()-date.fromisoformat(latest)).days if latest else None,
                    adjustment='none', default_codes=DEFAULT_CODES, sync=dict(state) if state else None)

    @app.post('/api/sync')
    def sync(payload: SyncRequest):
        if simulated:
            raise HTTPException(409, '当前为demo模式，请以STOCK_SOURCE=baostock启动')
        if not sync_lock.acquire(blocking=False):
            raise HTTPException(409, '同步进行中，请稍后重试')
        try:
            rows = download(payload.codes, payload.start, payload.end)
            save_market(path, provider.name, rows, payload.codes, payload.start, payload.end)
            return data_status()
        except DataError as exc:
            raise HTTPException(502, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            sync_lock.release()

    @app.get("/api/dates")
    def dates():
        with connect(path) as db:
            return [r[0] for r in db.execute('SELECT DISTINCT day FROM bars WHERE source=? ORDER BY day DESC', (provider.name,))]

    @app.get("/api/screen")
    def screen(day: date, limit: int = Query(10, ge=1, le=100)):
        result = snapshot(day)
        result["items"] = result["items"][:limit]
        return result

    @app.post("/api/reviews/{day}")
    def generate(day: date):
        result = snapshot(day)
        with connect(path) as db:
            db.execute('''INSERT INTO reviews(source,day,strategy,summary) VALUES(?,?,?,?)
              ON CONFLICT(source,day,strategy) DO UPDATE SET summary=excluded.summary''',
                       (provider.name, day.isoformat(), VERSION, json.dumps(result, ensure_ascii=False)))
        return review(day)

    @app.get("/api/reviews/{day}")
    def review(day: date):
        with connect(path) as db:
            row = db.execute('SELECT summary,notes FROM reviews WHERE source=? AND day=? AND strategy=?',
                             (provider.name, day.isoformat(), VERSION)).fetchone()
        if row is None:
            raise HTTPException(404, "尚未生成复盘")
        return dict(summary=json.loads(row["summary"]), notes=row["notes"])

    @app.put("/api/reviews/{day}/notes")
    def notes(day: date, payload: Note):
        review(day)
        with connect(path) as db:
            db.execute('UPDATE reviews SET notes=? WHERE source=? AND day=? AND strategy=?',
                       (payload.notes, provider.name, day.isoformat(), VERSION))
        return review(day)

    @app.get("/")
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return app


app = create_app()
