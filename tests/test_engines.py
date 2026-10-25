import csv
import io
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.csv_import import parse_csv
from app.engines import engine_score, technical_series
from app.main import create_app
from app.market import china_today
from app.storage import connect
from test_research import seed, holding


def rows(prices):
    return [dict(code='sh.600000', name='样本', day=(china_today()-timedelta(days=len(prices)-i)).isoformat(),
                 close=p, amount=3e8, is_st=0, suspended=0) for i,p in enumerate(prices)]


def test_quanti_known_cases():
    up=rows([10+i*.1 for i in range(70)])
    score,_=engine_score(up,'quanti_ma')
    ma5=sum(r['close'] for r in up[-5:])/5
    ma20=sum(r['close'] for r in up[-20:])/20
    ma60=sum(r['close'] for r in up[-60:])/60
    assert score==round(round(min((ma5/ma20-1+ma20/ma60-1)*10,1),3)*100,2)
    assert engine_score(rows([20-i*.1 for i in range(70)]),'quanti_ma')[0]==0
    assert engine_score(rows([20-i*.1 for i in range(20)]),'quanti_rsi')[0]==100
    assert engine_score(rows([10]*20),'quanti_rsi')[0]==0  # upstream zero-loss semantics
    assert engine_score(up[:59],'quanti_ma')[1]=='历史不足'


def test_chart_warmup_and_breakout():
    bars=rows([10+i*.01 for i in range(60)])
    points=technical_series(bars)
    assert points[0]['ma20'] is None and points[18]['ma20'] is None
    assert points[19]['ma20']==pytest.approx(10.095)
    assert points[-1]['ma60'] is not None
    assert engine_score(bars,'breakout')[0]==0
    bars[-1]['amount']=6e8
    assert engine_score(bars,'breakout')[0]>0


def test_engine_endpoints_watch_and_historical_isolation(tmp_path):
    path=tmp_path/'engine.db';seed(path)
    with TestClient(create_app(path,source='baostock')) as c:
        assert len(c.get('/api/engines').json())==4
        result=c.get('/api/engine-screen').json()
        assert len(result['items'])==2
        assert c.get('/api/engine-screen?engine=unknown').status_code==422
        day=(china_today()-timedelta(days=11)).isoformat()
        before=c.get('/api/series/sh.600000?day='+day).json()
        ranks=c.get('/api/engine-screen?day='+day).json()
        with connect(path) as db: db.execute('UPDATE bars SET close=10000 WHERE day>?',(day,))
        assert c.get('/api/series/sh.600000?day='+day).json()==before
        assert c.get('/api/engine-screen?day='+day).json()==ranks
        assert c.get('/api/series/sh.600999').status_code==404
        assert c.put('/api/watchlist',json={'code':'600000'}).json()[0]['code']=='sh.600000'
        c.put('/api/watchlist',json={'code':'600000'})
        assert len(c.get('/api/watchlist').json())==1
        assert c.put('/api/watchlist',json={'code':'bad'}).status_code==422
        assert c.delete('/api/watchlist/sh.600000').json()==[]
        assert c.get('/classic').status_code==200


def csv_text():
    out=io.StringIO();writer=csv.DictWriter(out,fieldnames=['code','name','day','close','amount']);writer.writeheader()
    for r in rows([10+i*.1 for i in range(65)]):
        writer.writerow({k:r[k] for k in writer.fieldnames})
    return out.getvalue()


def test_csv_transactional_failure_and_state_preservation(tmp_path):
    path=tmp_path/'csv.db';seed(path);holding(path)
    with TestClient(create_app(path,source='baostock')) as c:
        before=c.get('/api/instruments').json()
        assert c.post('/api/import-csv',json={'text':csv_text()}).status_code==422
        bad=csv_text().replace(',10.0,',',nan,')
        assert c.post('/api/import-csv',json={'text':bad,'replace_cache':True}).status_code==422
        assert c.get('/api/instruments').json()==before
        result=c.post('/api/import-csv',json={'text':csv_text(),'replace_cache':True})
        assert result.status_code==200 and result.json()['imported']==65
        assert len(c.get('/api/instruments').json())==1
        assert c.get('/api/data-status').json()['vendor']=='local_csv'
        assert c.get('/api/holdings').json()[0]['cost']==15
        assert c.get('/api/engine-screen').json()['items'][0]['verified'] is False
        assert c.post('/api/import-csv',json={'text':csv_text(),'replace_cache':True},headers={'Origin':'https://evil.example'}).status_code==403


@pytest.mark.parametrize('text',[
    'code,name,day,close,amount\n600000,测试,2099-01-01,10,100\n',
    'code,name,day,close,amount\n600000,测试,2026-01-01,-1,100\n',
    'code,name,day,close,amount\n600000,测试,2026-01-01,10,inf\n',
    'bad,columns\n1,2\n',
    'code,name,day,close,amount\n600000,测试,2026-01-01,10,100\n600000,测试,2026-01-01,10,100\n',
])
def test_csv_validation(text):
    with pytest.raises(ValueError): parse_csv(text)
