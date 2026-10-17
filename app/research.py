"""Explainable daily research; facts, conditional plans and missing data are explicit."""
from collections import defaultdict
from datetime import date
from math import floor
from statistics import mean

from .market import china_today
from .storage import connect
from .strategy import evaluate

BENCHMARK_NAMES = {'sh.000001':'上证指数', 'sh.000300':'沪深300', 'sz.399006':'创业板指'}


def indicators(rows):
    if len(rows) < 21:
        return None
    prices = [r['close'] for r in rows[-21:]]
    return dict(close=prices[-1], ma5=round(mean(prices[-5:]), 2),
                ma60=round(mean(r['close'] for r in rows[-60:]),2) if len(rows)>=60 else None,
                ma20=round(mean(prices[-20:]), 2), support=round(min(prices[-20:]),2),
                resistance=round(max(prices[-20:]),2),
                change_pct=round((prices[-1]/prices[-2]-1)*100,2),
                momentum_pct=round((prices[-1]/prices[0]-1)*100,2))


def candidate_plan(metrics, settings, equity, allowed):
    close = metrics['close']
    low, high = round(close*.99,2), round(close*1.01,2)
    stop = round(min(low*.99, max(metrics['support']*.99, low*(1-settings['max_loss_pct']/100))),2)
    gap = high-stop
    # Observation levels, not order prices; position limits assume a 100-share buy lot.
    budget = min(equity*settings['max_stock_pct']/100, settings['cash'],
                 equity*settings['risk_pct']/100/gap*high) if equity and gap>0 else 0
    shares = max(0, floor(budget/high/100)*100) if high>0 and allowed else 0
    return dict(observation_low=low, observation_high=high, invalidation=stop,
                review_level=metrics['resistance'], shares_upper_bound=shares,
                trigger='仅在指数趋势未转弱、收盘保持20期均线上方且成交恢复时考虑；盘中冲高不算确认。',
                invalidation_rule=f'收盘低于{stop:.2f}时取消候选逻辑；跳空可能导致损失超过预设。',
                sizing_note='单只仓位、现金与单笔风险三者取最小；各股上限独立计算，不能相加执行。100股仅为保守估算，特殊板块规则需人工核对。')


def build_report(path, source, requested_day=None):
    with connect(path) as db:
        settings=dict(db.execute('SELECT * FROM preferences WHERE id=1').fetchone())
        holdings=[dict(r) for r in db.execute('SELECT * FROM holdings ORDER BY code')]
        feed=db.execute('SELECT vendor,note FROM feed_status WHERE source=?',(source,)).fetchone()
        vendor=feed['vendor'] if feed else source
        feed_note=feed['note'] if feed else ''
        latest=db.execute('SELECT MAX(day) FROM bars WHERE source=?',(source,)).fetchone()[0]
        day=requested_day.isoformat() if requested_day else latest
        if day:
            rows=[dict(r) for r in db.execute('''SELECT b.*,c.sector,c.pe,c.pb FROM bars b
              LEFT JOIN context c ON b.source=c.source AND b.code=c.code AND b.day=c.day
              WHERE b.source=? AND b.day<=? ORDER BY b.code,b.day''',(source,day))]
            indices=[dict(r) for r in db.execute('SELECT * FROM benchmarks WHERE source=? AND day<=? ORDER BY code,day',(source,day))]
        else:
            rows,indices=[],[]
    simulated=source=='demo'
    age=(china_today()-date.fromisoformat(day)).days if day else None
    stale=age is None or age>4 or age<0
    groups=defaultdict(list)
    for row in rows: groups[row['code']].append(row)
    index_groups=defaultdict(list)
    for row in indices: index_groups[row['code']].append(row)
    market_indices=[]
    for code, series in index_groups.items():
        metric=indicators(series)
        if metric and series[-1]['day']==day:
            market_indices.append(dict(code=code,name=BENCHMARK_NAMES.get(code,code),**metric))
    above=sum(i['close']>=i['ma20'] for i in market_indices)
    regime='偏强' if len(market_indices)>=2 and above==len(market_indices) else '偏弱' if len(market_indices)>=2 and above==0 else '分化' if market_indices else '依据不足'
    current=[series for series in groups.values() if series[-1]['day']==day]
    daily=[]
    sectors=defaultdict(list)
    ranked=[]
    for series in current:
        metric=indicators(series)
        if metric:
            daily.append(metric['change_pct'])
            sector=series[-1].get('sector')
            if sector: sectors[sector].append(metric['change_pct'])
        score=evaluate(series)
        if score and metric:
            ranked.append(dict(**score,**{k:v for k,v in metric.items() if k not in score},
                               sector=series[-1].get('sector'),pe=series[-1].get('pe'),pb=series[-1].get('pb')))
    ranked.sort(key=lambda r:(-r['score'],r['code']))
    portfolio=[]
    known_value=0
    for holding in holdings:
        series=groups.get(holding['code'],[])
        if simulated or not series or series[-1]['day']!=day:
            portfolio.append(dict(**holding,status='行情缺失',action='先同步持仓行情',value=None,pnl=None,
                                  reason='不使用模拟或其他日期价格估算持仓盈亏。',plan=None))
            continue
        last=series[-1]
        value=round(last['close']*holding['quantity'],2)
        known_value+=value
        pnl=round((last['close']-holding['cost'])*holding['quantity'],2)
        pct=round((last['close']/holding['cost']-1)*100,2)
        metric=indicators(series)
        trend_line=(metric['ma60'] if holding['horizon']=='long' else metric['ma20']) if metric else None
        trend_period=60 if holding['horizon']=='long' else 20
        stop=round(holding['cost']*(1-settings['max_loss_pct']/100),2)
        reasons=[]
        if stale:
            status,action='缓存较旧','更新行情后复核'
        elif last['suspended'] not in (0,1) or last['is_st'] not in (0,1):
            status,action='交易状态未核验','仅复盘价格，核实ST与停牌状态后再定操作'
        elif last['suspended']:
            status,action='停牌','等待可交易状态，检查公告'
        elif last['is_st']:
            status,action='ST风险','优先复核持有必要性'
        elif last['close']<=stop:
            status,action='已触及风险线','优先复核减仓或退出条件'
        elif trend_line is None:
            status,action='历史不足','补齐数据，暂不加仓'
        elif last['close']<trend_line:
            status,action='趋势转弱',f'暂停加仓，观察能否收复{trend_period}期均线'
        else:
            status,action='趋势保持','继续观察，按风险线复核'
        if metric:
            reasons.append(f"收盘{last['close']:.2f}，当日{metric['change_pct']:+.2f}%；按{trend_period}期均线复核。")
        reasons.append('仅解释价格与趋势变化；未接入新闻、公告，不能判断真实涨跌原因。')
        plan=dict(risk_line=stop,trend_line=trend_line,
                  review_level=metric['resistance'] if metric else None,
                  trigger='先核实停牌/ST/公告与账户可卖数量；收盘触及风险线或趋势持续转弱时复核减仓或退出。',
                  invalidation='若收盘重新站稳20期均线，重新评估趋势；达到压力参考位只触发复盘，不自动止盈。')
        if status=='交易状态未核验':
            plan=None
        portfolio.append(dict(**holding,name=last['name'],close=last['close'],value=value,pnl=pnl,
                              pnl_pct=pct,status=status,action=action,reason=' '.join(reasons),plan=plan,
                              day=day))
    missing=sum(r['value'] is None for r in portfolio)
    equity=round(known_value+settings['cash'],2)
    invested_pct=round(known_value/equity*100,2) if equity else 0
    exposure_ok=not missing and invested_pct<settings['max_total_pct']
    for item in portfolio:
        item['weight_pct']=round(item['value']/equity*100,2) if item['value'] is not None and equity and not missing else None
        item['overweight']=item['weight_pct'] is not None and item['weight_pct']>settings['max_stock_pct']
        if item['overweight']:
            item['action']+='；单股超出设定仓位上限'
    allowed=not simulated and not stale and vendor!='tencent_fallback' and len(market_indices)>=2 and regime!='偏弱' and exposure_ok
    candidates=[]
    sector_counts=defaultdict(int)
    held_codes={h['code'] for h in holdings}
    for item in ranked:
        if item['code'] in held_codes or item['score']<65 or item['close']<item['ma20']:
            continue
        if item['pe'] is not None and item['pe']<=0:
            continue
        sector_key=item['sector'] or item['code']
        if sector_counts[sector_key]>=2:
            continue
        sector_counts[sector_key]+=1
        reasons=[f"规则评分{item['score']:.1f}/100，收盘高于20期均线，20期涨跌{item['momentum_pct']:+.2f}%。",
                 '成交额达到筛选门槛，当前非ST且未停牌。']
        if item['pe'] is not None: reasons.append(f"接口PE(TTM) {item['pe']:.1f}；未按行业估值，不代表便宜。")
        candidates.append(dict(**item,reasons=reasons,action='满足条件后观察机会' if allowed else '仅观察，暂不形成新增仓位计划',
                               plan=candidate_plan(item,settings,equity,allowed),
                               risks=['未验证盈利质量、财务真实性、公告与估值合理性，技术候选不等于基本面优质股。',
                                      '不复权价格可能受除权影响；不含滑点、涨跌停与可成交性判断。']))
        if len(candidates)>=5: break
    if equity:
        # Respect remaining aggregate exposure, as well as independent per-stock caps.
        remaining=max(0,equity*settings['max_total_pct']/100-known_value)
        for item in candidates:
            cap=floor(remaining/item['plan']['observation_high']/100)*100
            item['plan']['shares_upper_bound']=min(item['plan']['shares_upper_bound'],max(0,cap))
    priority={'已触及风险线':0,'ST风险':1,'停牌':2,'行情缺失':3,'缓存较旧':4,'趋势转弱':5,'历史不足':6,'趋势保持':7}
    portfolio.sort(key=lambda p:(priority.get(p['status'],9),p['code']))
    tasks=[]
    if vendor=='tencent_fallback': tasks.append(feed_note)
    if not day: tasks.append('先点击“一键更新行情”，获取研究股票池与持仓的真实日线。')
    if stale and day: tasks.append('缓存超过4个自然日或日期异常；仅显示历史复盘，更新前不形成新增仓位计划。')
    if len(market_indices)<2: tasks.append('指数依据不足；暂不形成新增仓位计划，不能把股票池涨跌当作全市场行情。')
    if not holdings: tasks.append('在“我的持仓”录入代码、成本、数量和持有逻辑。')
    if missing: tasks.append(f'{missing}只持仓行情缺失；更新时自动纳入股票池，总资产与仓位判断暂不完整。')
    if not exposure_ok and holdings: tasks.append('先处理持仓数据缺失或总仓位超过设定上限的问题。')
    if regime=='偏弱': tasks.append('所覆盖指数均低于20期均线；暂停新增仓位计划，优先复核持仓风险。')
    if settings['cash']==0: tasks.append('未录入可用现金，候选股的新增股数上限为0；请先填写账户与风险参数。')
    if not candidates and day and vendor!='tencent_fallback': tasks.append('当前股票池没有达到候选门槛的个股；允许空结果，不强行推荐。')
    tasks.extend(f"{p['code']}：{p['action']}" for p in portfolio if p['status'] not in ('趋势保持',))
    return dict(version='research-v1',source=source,vendor=vendor,feed_note=feed_note,simulated=simulated,day=day,age_days=age,stale=stale,
                market=dict(regime=regime,indices=market_indices,pool_size=len(groups),available=len(current),
                            up=sum(x>0 for x in daily),down=sum(x<0 for x in daily),
                            sectors=[dict(name=k,change_pct=round(mean(v),2),count=len(v))
                                     for k,v in sorted(sectors.items(),key=lambda x:-mean(x[1]))],
                            note='板块强弱仅为当前股票池内行业等权涨跌，不是全行业或全市场资金流。'),
                candidates=candidates,holdings=portfolio,settings=settings,tasks=tasks,
                account=dict(known_market_value=round(known_value,2),cash=settings['cash'],
                             equity=equity if not missing and (holdings or settings['cash']>0) else None,
                             invested_pct=invested_pct if not missing and equity>0 else None,
                             pnl=round(sum(p['pnl'] or 0 for p in portfolio),2) if portfolio else None,missing=missing),
                limitations=['按当前持仓快照复盘，不重建历史持仓；盈亏不含费用、分红或已实现收益。',
                             '阈值为可修改的研究规则，未验证收益。计划不构成自动委托；涨跌停、T+1和实际最小申报单位需核实。'])
