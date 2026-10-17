from datetime import date

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.backup_feed import parse
from app.main import create_app
from app.market import DataError
from test_market import bars,START,END


def payload(row):
    return dict(code=0,data={'sh600000':{'day':[row],'qt':{'sh600000':['1','测试股票']}}})


def test_amount_units_unknown_flags_and_adjustment():
    rows=parse(payload(['2026-01-05','10','11','12','9','100',{},'1','20000']),
               'sh.600000',START,END)
    assert rows[0]['amount']==2e8
    assert rows[0]['is_st']==-1 and rows[0]['suspended']==-1
    assert rows[0]['pe'] is None and rows[0]['pb'] is None
    with pytest.raises(DataError):
        parse(payload(['2026-01-05','10','11','12','9','100']),'sh.600000',START,END)
    with pytest.raises(DataError):
        parse(payload(['2026-01-05','10','nan','12','9','100',{},'1','20000']),'sh.600000',START,END)


def test_fallback_is_labelled_and_does_not_recommend(tmp_path,monkeypatch):
    def primary(*args): raise DataError('10002007')
    monkeypatch.setattr(main,'download',primary)
    rows=[dict(r,is_st=-1,suspended=-1) for r in bars()]
    monkeypatch.setattr(main,'download_backup',lambda *a:dict(rows=rows,benchmarks=[]))
    with TestClient(create_app(tmp_path/'data.db',source='baostock')) as c:
        c.put('/api/holdings',json={'code':'600000','cost':10,'quantity':100})
        result=c.post('/api/sync',json={'codes':['600000'],'start':str(START),'end':str(END)}).json()
        assert result['vendor']=='tencent_fallback'
        assert '腾讯备用' in result['message']
        report=c.get('/api/dashboard').json()
        assert report['vendor']=='tencent_fallback' and report['candidates']==[]
        assert report['holdings'][0]['value']==1250
        # Explicit recovery mode does not spend time on the failing primary source.
        def must_not_call(*args): raise AssertionError('primary should be skipped')
        monkeypatch.setattr(main,'download',must_not_call)
        assert c.post('/api/sync',json={'codes':['600000'],'start':str(START),'end':str(END),'feed':'backup'}).status_code==200
