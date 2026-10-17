"""Offline contract tests: no sockets, SDK server or TestClient required."""
import json
import subprocess
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import app.main as main
from app.main import Note, SyncRequest, create_app
from app.market import DataError, china_today, download, normalize_codes, validate_rows
from app.market_worker import fetch, records
from app.providers import get_provider
from app.storage import connect, initialize, save_market

START, END = date(2026, 1, 1), date(2026, 1, 31)


def bars(code='sh.600000'):
    return [dict(code=code, name='测试股票', day=f'2026-01-{i:02}', close=10+i/10,
                 amount=2e8, is_st=0, suspended=0) for i in range(1, 26)]


def endpoint(app, path, method='GET'):
    return next(r.endpoint for r in app.routes if getattr(r, 'path', None) == path and method in r.methods)


def test_request_validation():
    assert normalize_codes(['600519','SH.600519','000001','300750']) == ['sh.600519','sz.000001','sz.300750']
    for codes in [[], ['../../bad'], ['sh.000001'], ['bj.830001'], ['510300']]:
        with pytest.raises(ValueError): normalize_codes(codes)
    assert SyncRequest().end == china_today()-timedelta(days=1)
    for kwargs in [dict(end=china_today()), dict(start=END,end=START), dict(codes=['bad'])]:
        with pytest.raises(ValidationError): SyncRequest(**kwargs)


@pytest.mark.parametrize('changes', [dict(close=float('nan')),dict(amount=-1),dict(code='sz.000001'),
                                    dict(day='bad'),dict(is_st=3),dict(suspended=None)])
def test_reject_invalid_rows(changes):
    row = dict(bars()[0], **changes)
    with pytest.raises(DataError): validate_rows([row], ['sh.600000'], START, END)


def test_missing_duplicate_and_empty():
    for rows,codes in [([],['sh.600000']), (bars(),['sh.600000','sz.000001']),
                       ([bars()[0],bars()[0]],['sh.600000'])]:
        with pytest.raises(DataError): validate_rows(rows,codes,START,END)
    assert len(validate_rows(bars(),['sh.600000'],START,END)) == 25


def test_subprocess_retry_and_timeout(monkeypatch):
    calls=[]
    def fake_run(*args,**kwargs):
        calls.append(kwargs)
        if len(calls)==1: raise subprocess.TimeoutExpired('worker',90)
        return SimpleNamespace(returncode=0,stdout=json.dumps({'rows':bars()}))
    monkeypatch.setattr('app.market.subprocess.run',fake_run)
    assert len(download(['600000'],START,END)) == 25
    assert len(calls)==2 and calls[0]['timeout']==90
    monkeypatch.setattr('app.market.subprocess.run',lambda *a,**k: SimpleNamespace(returncode=0,stdout='invalid'))
    with pytest.raises(DataError,match='2次'): download(['600000'],START,END)


def test_real_source_cache_and_failure(tmp_path,monkeypatch):
    path=tmp_path/'market.sqlite3'
    initialize(path,get_provider('demo'))
    initialize(path,get_provider('baostock'))
    app=create_app(path,source='baostock')
    status=endpoint(app,'/api/data-status')
    sync=endpoint(app,'/api/sync','POST')
    assert status()['latest_day'] is None and not status()['simulated']
    request=SyncRequest(codes=['600000'],start=START,end=END)
    monkeypatch.setattr(main,'download',lambda *a: bars())
    assert sync(request)['sync']['row_count']==25
    screen=endpoint(app,'/api/screen')
    result=screen(date(2026,1,25),10)
    assert not result['simulated'] and result['source']=='baostock'
    assert result['universe']==1 and result['eligible']==1
    generate=endpoint(app,'/api/reviews/{day}','POST')
    notes=endpoint(app,'/api/reviews/{day}/notes','PUT')
    day=date(2026,1,25)
    generate(day); notes(day,Note(notes='研究记录'))
    def failing(*a): raise DataError('网络不可用')
    monkeypatch.setattr(main,'download',failing)
    with pytest.raises(HTTPException) as error: sync(request)
    assert error.value.status_code==502
    assert screen(day,10)==result
    monkeypatch.setattr(main,'download',lambda *a: bars())
    sync(request)  # lock released after failure
    assert generate(day)['notes']=='研究记录'
    with connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM bars WHERE source='demo'").fetchone()[0]==840
    # Successful pool replacement removes stale stocks, retaining demo and saved reviews.
    save_market(path,'baostock',bars('sz.000001'),['sz.000001'],START,END)
    assert screen(day,10)['items'][0]['code']=='sz.000001'
    assert endpoint(app,'/api/reviews/{day}')(day)['notes']=='研究记录'


class Result:
    def __init__(self,rows,error='0'):
        self.error_code=error; self.error_msg='failure'; self.fields=list(rows[0]) if rows else []
        self.rows=iter(rows); self.current=None
    def next(self):
        self.current=next(self.rows,None)
        return self.current is not None
    def get_row_data(self): return list(self.current.values())


def test_sdk_contract_and_logout():
    class SDK:
        logged_out=False
        def login(self): return SimpleNamespace(error_code='0')
        def logout(self): self.logged_out=True
        def query_stock_basic(self,code): return Result([dict(type='1',code_name='测试股票')])
        def query_history_k_data_plus(self,code,fields,**kwargs):
            assert kwargs['adjustflag']=='3' and kwargs['frequency']=='d'
            return Result([dict(date='2026-01-05',code=code,close='10.2',amount='200000000',tradestatus='0',isST='1')])
    sdk=SDK()
    data=fetch(sdk,dict(codes=['sh.600000'],start=str(START),end=str(END)))
    assert sdk.logged_out and data[0]['suspended']==1 and data[0]['is_st']==1
    sdk.logged_out=False
    sdk.query_stock_basic=lambda **kw: Result([],error='1')
    with pytest.raises(RuntimeError): fetch(sdk,dict(codes=['sh.600000']))
    assert sdk.logged_out
    with pytest.raises(RuntimeError): records(Result([],error='1'))


def test_demo_rejects_sync(tmp_path):
    path=tmp_path/'demo.sqlite3'
    initialize(path,get_provider('demo'))
    app=create_app(path,source='demo')
    with pytest.raises(HTTPException) as error:
        endpoint(app,'/api/sync','POST')(SyncRequest())
    assert error.value.status_code==409
