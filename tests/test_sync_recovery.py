import json
import socket
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.main import create_app
from app.market import DataError, download
from app.market_worker import GuardedSocket
from app.storage import connect,initialize,save_market
from app.providers import get_provider
from test_market import START, END, bars


class RawSocket:
    def __init__(self,data=b''):
        self.data=data;self.timeout=None;self.sent=None
    def settimeout(self,value): self.timeout=value
    def sendall(self,value): self.sent=value
    def recv(self,size): return self.data


def test_eof_is_error_instead_of_infinite_receive():
    raw=RawSocket();connection=GuardedSocket(raw)
    assert raw.timeout==10
    with pytest.raises(ConnectionError): connection.recv(8192)
    assert connection.send(b'hello')==5 and raw.sent==b'hello'
    raw.data=b'valid'
    assert connection.recv(8192)==b'valid'


def test_socket_timeout_is_propagated():
    raw=RawSocket()
    def timed_out(size): raise socket.timeout('timed out')
    raw.recv=timed_out
    with pytest.raises(socket.timeout): GuardedSocket(raw).recv(8192)


def test_network_error_retry_has_backoff_and_preserves_diagnostic(monkeypatch):
    calls=[];pauses=[]
    monkeypatch.setattr('app.market.time.sleep',lambda seconds: pauses.append(seconds))
    def run(*a,**kw):
        calls.append(kw)
        return SimpleNamespace(returncode=0,stdout=json.dumps({'error':'10002007','diagnostic':'connection reset'}))
    monkeypatch.setattr('app.market.subprocess.run',run)
    with pytest.raises(DataError,match='connection reset'): download(['600000'],START,END)
    assert len(calls)==2 and pauses==[2]


def test_same_day_success_is_distinct_from_failure(tmp_path,monkeypatch):
    bundle=dict(rows=bars(),benchmarks=[])
    monkeypatch.setattr(main,'download',lambda *a:bundle)
    with TestClient(create_app(tmp_path/'data.db',source='baostock')) as c:
        body={'codes':['600000'],'start':str(START),'end':str(END)}
        first=c.post('/api/sync',json=body).json()
        assert first['has_new_trading_day']
        second=c.post('/api/sync',json=body).json()
        assert not second['has_new_trading_day'] and '没有新增交易日' in second['message']
        before=c.get('/api/data-status').json()['sync']['updated_at']
        def fail(*args): raise DataError('connection reset')
        monkeypatch.setattr(main,'download',fail)
        monkeypatch.setattr(main,'download_backup',fail)
        assert c.post('/api/sync',json=body).status_code==502
        assert c.get('/api/data-status').json()['sync']['updated_at']==before


def test_lagging_supplier_rejected_against_calendar(monkeypatch):
    payload=dict(rows=bars(),benchmarks=[],expected_latest_day='2026-01-26')
    monkeypatch.setattr('app.market.time.sleep',lambda *_:None)
    monkeypatch.setattr('app.market.subprocess.run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=json.dumps(payload)))
    with pytest.raises(DataError,match='尚未更新'): download(['600000'],START,END,True)


def test_incremental_overlap_keeps_history_and_updates_corrections(tmp_path):
    path=tmp_path/'cache.db';initialize(path,get_provider('baostock'))
    original=bars()
    save_market(path,'baostock',original,['sh.600000'],START,END,[])
    new=[dict(r,close=99) for r in original if r['day']>='2026-01-20']
    save_market(path,'baostock',new,['sh.600000'],START,END,[],date(2026,1,20))
    with connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM bars WHERE source='baostock'").fetchone()[0]==25
        assert db.execute("SELECT close FROM bars WHERE day='2026-01-01'").fetchone()[0]==10.1
        assert db.execute("SELECT close FROM bars WHERE day='2026-01-20'").fetchone()[0]==99
        assert db.execute('SELECT row_count FROM sync_state').fetchone()[0]==25
