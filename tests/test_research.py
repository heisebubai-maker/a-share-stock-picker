from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.market import china_today
from app.providers import get_provider
from app.research import build_report
from app.storage import connect, initialize, save_market


def seed(path,age=1,indices=True):
    initialize(path,get_provider('baostock'))
    end=china_today()-timedelta(days=age)
    days=[(end-timedelta(days=69-i)).isoformat() for i in range(70)]
    rows=[]
    for code in ('sh.600000','sz.000001'):
        for i,day in enumerate(days):
            rows.append(dict(code=code,name='测试股票',day=day,close=10+i*.1,amount=3e8,
                             is_st=0,suspended=0,sector='测试行业',pe=12,pb=1.5))
    benchmarks=[dict(code=code,day=day,close=3000+i*10) for code in ('sh.000001','sh.000300','sz.399006')
                for i,day in enumerate(days)] if indices else []
    save_market(path,'baostock',rows,['sh.600000','sz.000001'],china_today()-timedelta(days=100),end,benchmarks)
    with connect(path) as db: db.execute('UPDATE preferences SET cash=100000')
    return end


def holding(path,code='sh.600000',cost=15,quantity=100,horizon='swing'):
    with connect(path) as db:
        db.execute('INSERT OR REPLACE INTO holdings VALUES(?,?,?,?,?,?)',(code,cost,quantity,horizon,'测试逻辑','now'))


def test_candidates_market_sizing_and_no_future_data(tmp_path):
    path=tmp_path/'test.db';end=seed(path)
    report=build_report(path,'baostock')
    assert report['market']['regime']=='偏强'
    assert report['market']['sectors'][0]['count']==2
    assert len(report['candidates'])==2
    p=report['candidates'][0]['plan']
    assert 0<p['shares_upper_bound'] and p['shares_upper_bound']%100==0
    assert p['shares_upper_bound']*p['observation_high']<=20000
    assert p['invalidation']<p['observation_low']<p['observation_high']
    history=build_report(path,'baostock',end-timedelta(days=10))
    assert history['candidates'][0]['close']<report['candidates'][0]['close']
    assert history['stale'] and all(c['plan']['shares_upper_bound']==0 for c in history['candidates'])


@pytest.mark.parametrize('case',['stale','no_indices','cash_zero','missing_holding','max_exposure'])
def test_no_sizing_when_evidence_or_budget_missing(tmp_path,case):
    path=tmp_path/'test.db';seed(path,age=10 if case=='stale' else 1,indices=case!='no_indices')
    if case=='cash_zero':
        with connect(path) as db: db.execute('UPDATE preferences SET cash=0')
    if case=='missing_holding': holding(path,code='sh.600519')
    if case=='max_exposure':
        holding(path,quantity=100000)
    report=build_report(path,'baostock')
    assert all(c['plan']['shares_upper_bound']==0 for c in report['candidates'])
    if case=='missing_holding':
        assert report['account']['equity'] is None
        assert report['holdings'][0]['value'] is None


def test_holdings_pnl_risk_and_horizon(tmp_path):
    path=tmp_path/'test.db';seed(path)
    holding(path,cost=20,quantity=200,horizon='long')
    report=build_report(path,'baostock')
    h=report['holdings'][0]
    assert h['pnl']==-620 and h['value']==3380
    assert h['status']=='已触及风险线' and h['plan']['risk_line']==18.4
    assert h['plan']['trend_line']<16  # 60-period MA, not 20-period
    assert all(c['code']!=h['code'] for c in report['candidates'])
    demo=build_report(path,'demo')
    assert demo['holdings'][0]['value'] is None and demo['account']['equity'] is None


def test_portfolio_api_and_saved_snapshot(tmp_path):
    path=tmp_path/'test.db';seed(path)
    with TestClient(create_app(path,source='baostock')) as c:
        assert c.put('/api/holdings',json={'code':'600000','cost':15,'quantity':100,'thesis':'<script>test</script>'}).status_code==200
        assert c.get('/api/dashboard').json()['holdings'][0]['pnl']==190
        assert c.put('/api/holdings',json={'code':'600000','cost':15,'quantity':-1}).status_code==422
        assert c.put('/api/holdings',json={'code':'600000','cost':15,'quantity':1.5}).status_code==422
        assert c.put('/api/preferences',json={'max_stock_pct':80,'max_total_pct':70}).status_code==422
        assert c.post('/api/research-reports').status_code==200
        day=c.get('/api/research-reports').json()[0]['day']
        assert c.delete('/api/holdings/sh.600000').status_code==200
        assert c.get('/api/dashboard').json()['holdings']==[]
        saved=c.get('/api/research-reports/'+day).json()
        assert saved['holdings'][0]['quantity']==100
        assert c.get('/api/research-reports/2000-01-01').status_code==404
    with TestClient(create_app(path,source='baostock')) as c:
        assert len(c.get('/api/research-reports').json())==1


def test_empty_first_start(tmp_path):
    path=tmp_path/'test.db'
    with TestClient(create_app(path,source='baostock')) as c:
        report=c.get('/api/dashboard').json()
        assert report['day'] is None and report['market']['regime']=='依据不足'
        assert c.post('/api/research-reports').status_code==409
        assert c.get('/api/research-reports').json()==[]


def test_weak_market_and_loss_making_filter(tmp_path):
    path=tmp_path/'test.db';seed(path)
    with connect(path) as db:
        for code in ('sh.000001','sh.000300','sz.399006'):
            rows=db.execute('SELECT day FROM benchmarks WHERE code=? ORDER BY day',(code,)).fetchall()
            for i,row in enumerate(rows):
                db.execute('UPDATE benchmarks SET close=? WHERE code=? AND day=?',(4000-i*10,code,row[0]))
        db.execute("UPDATE context SET pe=-12 WHERE code='sh.600000'")
    report=build_report(path,'baostock')
    assert report['market']['regime']=='偏弱'
    assert all(c['plan']['shares_upper_bound']==0 for c in report['candidates'])
    assert all(c['code']!='sh.600000' for c in report['candidates'])


def test_long_holding_needs_60_bars_and_missing_blocks(tmp_path):
    path=tmp_path/'test.db';end=seed(path)
    holding(path,horizon='long')
    with connect(path) as db:
        db.execute('DELETE FROM bars WHERE day<?',((end-timedelta(days=29)).isoformat(),))
    report=build_report(path,'baostock')
    assert report['holdings'][0]['status']=='历史不足'
    assert report['holdings'][0]['plan']['trend_line'] is None
