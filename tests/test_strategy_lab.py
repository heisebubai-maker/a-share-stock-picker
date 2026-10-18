from datetime import timedelta
import time

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

import app.main as main
from app.main import create_app
from app.strategy_lab import StrategyConfig, assess
from app.storage import connect
from app.universe import select
from app.validation import study
from test_research import seed, holding


def history(path):
    with connect(path) as db:
        return [dict(r) for r in db.execute("SELECT * FROM bars WHERE code='sh.600000' ORDER BY day")]


def test_persistence_changes_results_and_validates(tmp_path):
    path=tmp_path/'lab.db';seed(path)
    with TestClient(create_app(path,source='baostock')) as c:
        assert len(c.get('/api/dashboard').json()['candidates'])==2
        config=c.get('/api/strategies').json()['active']
        config.update(name='高门槛',min_amount=100)
        assert c.put('/api/strategies',json=config).status_code==200
        report=c.get('/api/dashboard').json()
        assert report['candidates']==[] and report['rejections']['成交额不足']==2
        for change in ({'top_k':0},{'min_momentum':51,'max_momentum':50},{'momentum_weight':0,'trend_weight':0,'stability_weight':0,'liquidity_weight':0}):
            assert c.put('/api/strategies',json=dict(config,**change)).status_code==422
    with TestClient(create_app(path,source='baostock')) as c:
        assert c.get('/api/strategies').json()['active']['name']=='高门槛'


def test_modes_unknown_status_and_no_future(tmp_path):
    path=tmp_path/'lab.db';seed(path);rows=history(path)
    config=StrategyConfig(min_score=0)
    result,_=assess(rows,config)
    assert result and sum(result['factors'].values())==pytest.approx(result['score'])
    assert assess(rows,config.model_copy(update={'mode':'breakout'}))[0] is None
    boosted=[dict(r) for r in rows];boosted[-1]['amount']=8e8
    assert assess(boosted,config.model_copy(update={'mode':'breakout'}))[0]
    assert assess(rows,config.model_copy(update={'mode':'value'}))[1]=='估值缺失或超限'
    assert assess(rows[:20],config)[1]=='历史不足'
    unknown=[dict(r,is_st=-1,suspended=-1) for r in rows]
    assert assess(unknown,config)[0]['verified'] is False
    assert assess(unknown,config.model_copy(update={'allow_unverified':False}))[0] is None
    with connect(path) as db: db.execute('UPDATE bars SET is_st=-1,suspended=-1')
    with TestClient(create_app(path,source='baostock')) as c:
        report=c.get('/api/dashboard').json()
        assert report['candidates'] and all(p['plan']['shares_upper_bound']==0 for p in report['candidates'])
    # Future prices in the database cannot change a historical report.
    from app.research import build_report
    from datetime import date
    asof=date.fromisoformat(rows[59]['day'])
    before=build_report(path,'baostock',asof)['candidates']
    with connect(path) as db: db.execute('UPDATE bars SET close=9999 WHERE day>?',(str(asof),))
    assert build_report(path,'baostock',asof)['candidates']==before


def test_snapshot_filters_units_board_and_ceiling():
    row=dict(symbol='sz300001',name='测试',trade=20,amount=3e8,mktcap=1000000,changepercent=5,turnoverratio=3)
    rows=[row,dict(row,symbol='sh600001',mktcap=30000000),dict(row,symbol='sz300002',name='ST测试'),dict(row,symbol='sz300003',changepercent=20),dict(row,symbol='bj920001')]
    result=select(rows,StrategyConfig(max_cap=200,board='growth'))
    assert result['total']==5 and result['supported']==4 and result['qualified']==1
    assert result['items'][0]['cap']==100 and result['items'][0]['code']=='sz.300001'


def test_study_next_day_entry_and_cost(tmp_path):
    path=tmp_path/'lab.db';seed(path);config=StrategyConfig(min_score=0)
    a=study(path,'baostock',config,cost_pct=0)
    b=study(path,'baostock',config,cost_pct=.5)
    assert a['count']>0 and a['mean_pct']-b['mean_pct']==pytest.approx(.5)
    assert all(s['signal_day']<s['entry_day']<s['exit_day'] for s in a['samples'])


def test_market_job_keeps_holdings_and_failure_preserves_cache(tmp_path,monkeypatch):
    path=tmp_path/'lab.db';seed(path);holding(path)
    monkeypatch.setattr(main,'scan',lambda *a:dict(total=5000,supported=4500,qualified=100,items=[{'code':'sz.000001'}]))
    captured=[]
    def fail(codes,*args):
        captured.extend(codes)
        raise main.DataError('测试断线')
    monkeypatch.setattr(main,'download_backup',fail)
    with TestClient(create_app(path,source='baostock')) as c:
        old=c.get('/api/data-status').json()['sync']
        assert c.post('/api/update',json={'universe':'market','feed':'backup'}).status_code==200
        for _ in range(100):
            state=c.get('/api/update-status').json()
            if state['state']!='running': break
            time.sleep(.02)
        assert state['state']=='error'
        assert set(captured)=={'sh.600000','sz.000001'}
        assert c.get('/api/data-status').json()['sync']==old
        assert c.get('/api/dashboard').json()['scan'] is None
