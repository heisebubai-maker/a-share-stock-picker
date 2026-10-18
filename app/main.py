import json
import os
from contextlib import asynccontextmanager
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from threading import Lock, Thread
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator, ConfigDict

from .providers import get_provider
from .storage import connect, initialize, save_market
from .strategy import VERSION, evaluate
from .market import DEFAULT_CODES, DataError, china_today, download, normalize_codes
from .research import build_report
from .backup_feed import download_backup
from .strategy_lab import StrategyConfig, PRESETS, load_strategy
from .universe import scan
from .validation import study

ROOT = Path(__file__).resolve().parent


class Note(BaseModel):
    notes: str = Field(max_length=5000)


class Holding(BaseModel):
    model_config=ConfigDict(allow_inf_nan=False)
    code: str
    cost: float = Field(gt=0,le=1000000)
    quantity: int = Field(gt=0,le=100000000,strict=True)
    horizon: Literal['swing','long'] = 'swing'
    thesis: str = Field(default='',max_length=1000)

    @model_validator(mode='after')
    def normalize(self):
        self.code=normalize_codes([self.code])[0]
        return self


class Preferences(BaseModel):
    model_config=ConfigDict(allow_inf_nan=False)
    cash: float=Field(default=0,ge=0,le=1e12)
    max_stock_pct: float=Field(default=20,gt=0,le=100)
    max_total_pct: float=Field(default=70,gt=0,le=100)
    max_loss_pct: float=Field(default=8,ge=1,le=30)
    risk_pct: float=Field(default=1,gt=0,le=5)

    @model_validator(mode='after')
    def consistent(self):
        if self.max_stock_pct>self.max_total_pct:
            raise ValueError('单只仓位上限不能超过总仓位上限')
        return self


class SyncRequest(BaseModel):
    universe: Literal['custom','market'] = 'custom'
    feed: Literal['auto','backup'] = 'auto'
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
    job_lock=Lock()
    job=dict(state='idle',message='尚未更新',started_at=None,finished_at=None)

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
            feed=db.execute('SELECT vendor,note FROM feed_status WHERE source=?',(provider.name,)).fetchone()
        return dict(source=provider.name, simulated=simulated, latest_day=latest,
                    age_days=(china_today()-date.fromisoformat(latest)).days if latest else None,
                    adjustment='none', default_codes=DEFAULT_CODES, sync=dict(state) if state else None,
                    vendor=feed['vendor'] if feed else provider.name,feed_note=feed['note'] if feed else '')

    @app.post('/api/sync')
    def sync(payload: SyncRequest):
        if simulated:
            raise HTTPException(409, '当前为demo模式，请以STOCK_SOURCE=baostock启动')
        if not sync_lock.acquire(blocking=False):
            raise HTTPException(409, '同步进行中，请稍后重试')
        try:
            before=data_status()
            previous=before['latest_day']
            with connect(path) as db:
                held=[r[0] for r in db.execute('SELECT code FROM holdings')]
            codes=normalize_codes(payload.codes+held)
            refresh_from=None
            cached=before['sync']
            with connect(path) as db:
                index_count=db.execute('SELECT COUNT(*) FROM benchmarks WHERE source=?',(provider.name,)).fetchone()[0]
                cached_rows=db.execute('''SELECT b.code,b.name,c.sector FROM bars b LEFT JOIN context c
                  ON b.source=c.source AND b.code=c.code AND b.day=c.day
                  WHERE b.source=? ORDER BY b.day DESC''',(provider.name,)).fetchall()
            metadata={}
            # Refresh names/industry every Monday even when daily sync keeps the cache timestamp fresh.
            if cached and china_today().weekday()!=0 and (datetime.now(timezone.utc)-datetime.fromisoformat(cached['updated_at'])).total_seconds()<7*86400:
                for item in cached_rows:
                    metadata.setdefault(item['code'],dict(name=item['name'],sector=item['sector']))
            if (cached and previous and set(json.loads(cached['codes']))==set(codes) and index_count>=63 and
                    payload.start>=date.fromisoformat(cached['start']) and payload.end>=date.fromisoformat(previous)):
                refresh_from=max(payload.start,date.fromisoformat(previous)-timedelta(days=10))
            vendor,note=provider.name,''
            try:
                if payload.feed=='backup':
                    raise DataError('已选择备用线路')
                bundle = download(codes, refresh_from or payload.start, payload.end, True, metadata)
            except DataError as primary_error:
                with job_lock:
                    if job['state']=='running': job['message']='正在通过腾讯HTTPS备用线路读取真实日线…'
                try:
                    bundle=download_backup(codes,refresh_from or payload.start,payload.end,metadata)
                except DataError as backup_error:
                    raise DataError(f'主线路和备用线路均未更新成功。{primary_error}；{backup_error}') from backup_error
                vendor='tencent_fallback'
                note='近期价格与成交额来自腾讯HTTPS备用线路；早期历史可含BaoStock缓存。ST/停牌状态未取得，仅显示待核验观察名单，暂停新增仓位计划。行业仅为缓存参考，PE/PB未补造。'
            save_market(path, provider.name, bundle['rows'], codes, payload.start, payload.end,bundle['benchmarks'],refresh_from,vendor,note)
            result=data_status()
            latest=result['latest_day']
            result['has_new_trading_day']=previous is None or latest>previous
            result['message']=(f'已同步新交易日 {latest}，持仓与候选复盘已刷新' if result['has_new_trading_day']
                               else f'已联网核对行情，最新交易日仍为 {latest}，没有新增交易日；复盘已刷新')
            if vendor=='tencent_fallback':
                result['message']+='。已使用腾讯备用日线；交易状态未核验，暂停新增计划'
            return result
        except DataError as exc:
            raise HTTPException(502, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            sync_lock.release()

    @app.get('/api/dashboard')
    def dashboard(day: date | None = None):
        return build_report(path,provider.name,day)

    @app.get('/api/strategies')
    def strategies():
        with connect(path) as db:
            profiles=[json.loads(r[0]) for r in db.execute('SELECT payload FROM strategy_profiles ORDER BY name')]
        return dict(active=load_strategy(path).model_dump(),presets=PRESETS,profiles=profiles)

    @app.get('/api/strategy-study')
    def strategy_study(horizon: int = Query(5,ge=1,le=20),cost_pct: float = Query(.3,ge=0,le=5)):
        return study(path,provider.name,load_strategy(path),horizon,cost_pct)

    @app.put('/api/strategies')
    def save_strategy(payload: StrategyConfig):
        with job_lock:
            if job['state']=='running': raise HTTPException(409,'更新期间不能切换策略，请等待完成')
            with connect(path) as db:
                count=db.execute('SELECT COUNT(*) FROM strategy_profiles').fetchone()[0]
                if count>=30 and not db.execute('SELECT 1 FROM strategy_profiles WHERE name=?',(payload.name,)).fetchone():
                    raise HTTPException(422,'最多保存30个策略方案')
                db.execute('UPDATE strategy_profiles SET active=0')
                db.execute('INSERT OR REPLACE INTO strategy_profiles VALUES(?,?,1)',(payload.name,payload.model_dump_json()))
        return strategies()

    @app.get('/api/holdings')
    def holdings():
        with connect(path) as db:
            return [dict(r) for r in db.execute('SELECT * FROM holdings ORDER BY code')]

    @app.put('/api/holdings')
    def save_holding(payload: Holding):
        with connect(path) as db:
            count=db.execute('SELECT COUNT(*) FROM holdings').fetchone()[0]
            exists=db.execute('SELECT 1 FROM holdings WHERE code=?',(payload.code,)).fetchone()
            if count>=50 and not exists:
                raise HTTPException(422,'最多记录50只持仓')
            db.execute('INSERT OR REPLACE INTO holdings VALUES(?,?,?,?,?,?)',
                       (payload.code,payload.cost,payload.quantity,payload.horizon,payload.thesis,
                        datetime.now(timezone.utc).isoformat()))
        return holdings()

    @app.delete('/api/holdings/{code}')
    def remove_holding(code: str):
        try: code=normalize_codes([code])[0]
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc
        with connect(path) as db:
            db.execute('DELETE FROM holdings WHERE code=?',(code,))
        return holdings()

    @app.get('/api/preferences')
    def preferences():
        with connect(path) as db:
            return dict(db.execute('SELECT * FROM preferences WHERE id=1').fetchone())

    @app.put('/api/preferences')
    def save_preferences(payload: Preferences):
        with connect(path) as db:
            db.execute('UPDATE preferences SET cash=?,max_stock_pct=?,max_total_pct=?,max_loss_pct=?,risk_pct=? WHERE id=1',
                       (payload.cash,payload.max_stock_pct,payload.max_total_pct,payload.max_loss_pct,payload.risk_pct))
        return preferences()

    def store_report():
        report=build_report(path,provider.name)
        if not report['day']:
            raise HTTPException(409,'暂无行情，先更新行情再保存复盘')
        with connect(path) as db:
            db.execute('INSERT OR REPLACE INTO research_reports VALUES(?,?,?,?)',
                       (provider.name,report['day'],json.dumps(report,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
        return report

    @app.post('/api/research-reports')
    def save_report():
        return store_report()

    @app.get('/api/research-reports')
    def report_history():
        with connect(path) as db:
            return [dict(r) for r in db.execute('SELECT day,created_at FROM research_reports WHERE source=? ORDER BY day DESC',(provider.name,))]

    @app.get('/api/research-reports/{day}')
    def saved_report(day: date):
        with connect(path) as db:
            row=db.execute('SELECT payload FROM research_reports WHERE source=? AND day=?',(provider.name,day.isoformat())).fetchone()
        if not row: raise HTTPException(404,'该日尚未保存复盘')
        return json.loads(row['payload'])

    @app.get('/api/update-status')
    def update_status():
        with job_lock:
            return dict(job)

    @app.post('/api/update')
    def update(payload: SyncRequest):
        if simulated: raise HTTPException(409,'模拟模式无法同步真实行情')
        with job_lock:
            if job['state']=='running': raise HTTPException(409,'更新进行中，请稍候')
            job.update(state='running',message='正在获取股票、持仓、行业及指数日线…',
                       started_at=datetime.now(timezone.utc).isoformat(),finished_at=None)
        def work():
            try:
                if payload.universe=='market':
                    with job_lock: job['message']='正在扫描全市场快照，按策略初筛，随后下载入围股票日线…'
                    with connect(path) as db:
                        held=[r[0] for r in db.execute('SELECT code FROM holdings')]
                    slots=min(40,50-len(held))
                    if slots<1: raise DataError('持仓已占满50只，请使用自选池更新')
                    config=load_strategy(path)
                    universe=scan(config,slots)
                    payload.codes=list(dict.fromkeys([i['code'] for i in universe['items']]+held))
                    with job_lock: job['message']=f"扫描{universe['total']}只，初筛合格{universe['qualified']}只；正在下载{len(payload.codes)}只日线…"
                result=sync(payload)
                with connect(path) as db:
                    if payload.universe=='market':
                        universe['strategy']=config.model_dump()
                        db.execute('INSERT OR REPLACE INTO universe_scan VALUES(1,?)',(json.dumps(universe,ensure_ascii=False),))
                    else: db.execute('DELETE FROM universe_scan')
                store_report()
                state,message='done',result['message']
            except Exception as exc:
                state,message='error',str(exc.detail if isinstance(exc,HTTPException) else exc)
            with job_lock:
                job.update(state=state,message=message,finished_at=datetime.now(timezone.utc).isoformat())
        Thread(target=work,daemon=True).start()
        return update_status()

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
