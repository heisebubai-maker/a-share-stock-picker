import json
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .providers import get_provider
from .storage import connect, initialize
from .strategy import VERSION, evaluate

ROOT = Path(__file__).resolve().parent


class Note(BaseModel):
    notes: str = Field(max_length=5000)


def create_app(db_path=None, source=None):
    path = db_path or os.environ.get("STOCK_DB", str(ROOT.parent / "data" / "stock.sqlite3"))
    provider = get_provider(source or os.environ.get("STOCK_SOURCE", "demo"))

    @asynccontextmanager
    async def lifespan(app):
        initialize(path, provider)
        yield

    app = FastAPI(title="A股选股复盘 · 模拟研究版", lifespan=lifespan)

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
        return dict(day=day.isoformat(), source=provider.name, simulated=True,
                    strategy=VERSION, universe=len(groups), eligible=len(ranked), items=ranked)

    @app.get("/api/health")
    def health():
        with connect(path) as db:
            db.execute('SELECT 1').fetchone()
        return dict(status="ok", source=provider.name, simulated=True)

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
