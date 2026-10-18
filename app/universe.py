"""Sina market snapshot preselection; not a historical universe or trading-status feed."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from math import ceil, isfinite
import re
import httpx

from .market import DataError, normalize_codes
from .strategy_lab import board_matches

BASE='https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.'


def select(rows, config, limit=40):
    qualified=[]
    supported=0
    for row in rows:
        try:
            symbol=row['symbol']
            code=normalize_codes([symbol[:2]+'.'+symbol[2:]])[0]
            supported+=1
            name=str(row['name'])
            if not board_matches(code,config.board) or 'ST' in name.upper() or '退' in name or name.startswith(('N','C')): continue
            close,amount,cap,change,turnover=[float(row[k]) for k in ('trade','amount','mktcap','changepercent','turnoverratio')]
            if not all(isfinite(x) for x in (close,amount,cap,change,turnover)): continue
            if close<=0 or cap<=0 or amount<config.min_amount*1e8 or cap/10000>config.max_cap: continue
            if change>config.max_daily_change: continue
            if config.mode=='value':
                pe=float(row.get('per') or 0)
                if not isfinite(pe) or not 0<pe<=config.max_pe: continue
                priority=-pe
            elif config.mode=='pullback': priority=-abs(change)+min(turnover,10)*.1
            else: priority=change+min(turnover,10)*.2
            qualified.append(dict(code=code,name=name,change_pct=change,cap=round(cap/10000,2),priority=priority))
        except (ValueError,TypeError,KeyError): continue
    qualified.sort(key=lambda r:(-r['priority'],r['code']))
    return dict(total=len(rows),supported=supported,qualified=len(qualified),items=qualified[:limit],
                fetched_at=datetime.now(timezone.utc).isoformat(),
                note='新浪当前快照初筛（不含北交所）；快照无交易日期，仅用于发现股票。日线复筛最多40只，非全市场历史回测。市值限制仅在初筛执行。')


def scan(config, limit=40):
    try:
        with httpx.Client(timeout=15,headers={'User-Agent':'Mozilla/5.0'},follow_redirects=True) as client:
            response=client.get(BASE+'getHQNodeStockCount',params={'node':'hs_a'})
            response.raise_for_status()
            count=int(re.fullmatch(r'\s*"?(\d+)"?\s*',response.text).group(1))
            if not 1000<=count<=10000: raise ValueError('股票数量异常')
            def page(number):
                result=client.get(BASE+'getHQNodeData',params=dict(page=number,num=80,sort='symbol',asc=1,node='hs_a',symbol='',_s_r_a='page'))
                result.raise_for_status()
                data=result.json()
                if not isinstance(data,list) or not data: raise ValueError('分页缺失')
                return data
            with ThreadPoolExecutor(max_workers=3) as pool:
                pages=list(pool.map(page,range(1,ceil(count/80)+1)))
        rows=[r for p in pages for r in p]
        if len({r['symbol'] for r in rows})!=count or len(rows)!=count:
            raise ValueError('分页数量变化或重复，请稍后重试')
        result=select(rows,config,limit)
        if not result['items']: raise ValueError('初筛没有结果，请调整市值、成交额或板块范围')
        return result
    except (httpx.HTTPError,ValueError,TypeError,KeyError,AttributeError) as exc:
        raise DataError(f'全市场初筛失败，原行情保留：{exc}') from exc
