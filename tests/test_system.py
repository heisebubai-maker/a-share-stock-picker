from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.providers import DemoProvider, get_provider
from app.strategy import evaluate


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / 'test.sqlite3', source='demo')) as c:
        yield c


def test_screen_and_validation(client):
    assert client.get('/api/health').json()['simulated']
    days = client.get('/api/dates').json()
    data = client.get('/api/screen', params={'day': days[0]}).json()
    assert data['eligible'] == 10 and data['universe'] == 12
    assert all(0 <= r['score'] <= 100 for r in data['items'])
    assert [r['score'] for r in data['items']] == sorted([r['score'] for r in data['items']], reverse=True)
    assert client.get('/api/screen?day=2026-10-18').status_code == 404
    assert client.get('/api/screen?day=bad').status_code == 422
    assert client.get('/api/screen?day=2026-10-16&limit=0').status_code == 422
    assert client.get('/api/screen', params={'day':days[-1]}).json()['eligible'] == 0


def test_review_persistence_and_idempotency(tmp_path):
    path = tmp_path / 'persistent.sqlite3'
    for iteration in range(2):
        with TestClient(create_app(path, source='demo')) as c:
            day = c.get('/api/dates').json()[0]
            url = '/api/reviews/' + day
            if iteration == 0:
                assert c.get(url).status_code == 404
                assert c.put(url+'/notes', json={'notes':'x'}).status_code == 404
                assert c.post(url).status_code == 200
                assert c.put(url+'/notes', json={'notes':'复盘 <script>test</script>'}).status_code == 200
            assert c.post(url).json()['notes'] == '复盘 <script>test</script>'
            assert c.put(url+'/notes',json={'notes':'x'*5001}).status_code == 422
            assert c.get('/api/screen?day='+day).json()['universe'] == 12


def test_filters_and_future_data(client):
    rows = [r for r in DemoProvider().bars() if r['code']=='DEMO01']
    assert evaluate(rows[:20]) is None
    for field,value in [('is_st',1),('suspended',1),('close',0),('close',float('nan'))]:
        bad=deepcopy(rows); bad[-1][field]=value
        assert evaluate(bad) is None
    bad=deepcopy(rows)
    for row in bad: row['amount']=1
    assert evaluate(bad) is None
    day=rows[30]['day']
    expected=evaluate(rows[:31])
    actual=client.get('/api/screen?day='+day).json()['items']
    assert next(r for r in actual if r['code']=='DEMO01') == expected


def test_static_and_cross_origin(client):
    assert '真实日线同步' in client.get('/').text
    assert client.get('/static/app.js').status_code == 200
    assert client.post('/api/reviews/2026-10-16',headers={'Origin':'https://evil.example'}).status_code == 403
    with pytest.raises(ValueError): get_provider('live')
