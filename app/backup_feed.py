"""Explicit degraded HTTPS daily feed; unknown trading flags are never invented."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from math import isfinite

import httpx

from .market import DataError,normalize_codes

ENDPOINT='https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get'
INDEX_CODES=('sh.000001','sh.000300','sz.399006')


def parse(payload,code,start,end,index=False):
    symbol=code.replace('.','')
    try:
        if payload.get('code')!=0:
            raise ValueError('provider error')
        body=payload['data'][symbol]
        raw=body['day']  # Only unadjusted day series is accepted.
        quotes=body.get('qt',{}).get(symbol,[])
        name=str(quotes[1])[:80] if len(quotes)>1 else code
        result=[];seen=set()
        for values in raw:
            day=date.fromisoformat(values[0])
            if not start<=day<=end: continue
            close=float(values[2])
            if not isfinite(close) or close<=0 or day in seen: raise ValueError('invalid close/date')
            seen.add(day)
            row=dict(code=code,day=day.isoformat(),close=close)
            if not index:
                # newfqkline amount is in 10,000 CNY; older 6-field endpoints are rejected.
                amount=float(values[8])*10000
                if not isfinite(amount) or amount<0: raise ValueError('invalid amount')
                row.update(name=name,amount=amount,is_st=-1,suspended=-1,sector=None,pe=None,pb=None)
            result.append(row)
        if not result: raise ValueError('empty daily data')
        return sorted(result,key=lambda r:r['day'])
    except (KeyError,TypeError,ValueError,IndexError,AttributeError) as exc:
        raise DataError(f'腾讯备用日线{code}返回不完整，未覆盖缓存') from exc


def download_backup(codes,start,end,cached_metadata=None):
    codes=normalize_codes(codes)
    metadata=cached_metadata or {}
    with httpx.Client(timeout=httpx.Timeout(12,connect=8),follow_redirects=True) as client:
        def fetch(code):
            try:
                response=client.get(ENDPOINT,params={'param':f"{code.replace('.','')},day,{start},{end},640,"})
                response.raise_for_status()
                result=parse(response.json(),code,start,end,index=code in INDEX_CODES)
                for row in result:
                    if code in metadata:
                        row['sector']=metadata[code].get('sector')
                return result
            except (httpx.HTTPError,ValueError) as exc:
                raise DataError(f'腾讯备用线路{code}连接失败：{type(exc).__name__}') from exc
        with ThreadPoolExecutor(max_workers=3) as pool:
            series=list(pool.map(fetch,codes+list(INDEX_CODES)))
    return dict(rows=[r for group in series[:len(codes)] for r in group],
                benchmarks=[r for group in series[len(codes):] for r in group])
