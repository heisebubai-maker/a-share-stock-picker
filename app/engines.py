"""Audited Quanti screeners and ta indicators, isolated from order execution."""
from collections import defaultdict
from math import isfinite
from statistics import mean

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD, SMAIndicator
from ta.volatility import BollingerBands

from .storage import connect
from .vendor.quanti.ma_trend import MATrendScreener
from .vendor.quanti.rsi_oversold import RSIOversoldScreener
from .vendor.quanti.support import BarData

ENGINES = {
    'quanti_ma': dict(name='Quanti · 均线多头', min_history=60,
                     description='直接运行Quanti算法：MA5 > MA20 > MA60，收盘不低于MA5；按均线间距排序。',
                     origin='coo-moon/quanti · MATrendScreener（MIT）'),
    'quanti_rsi': dict(name='Quanti · RSI超卖', min_history=15,
                      description='直接运行Quanti算法：最近14期简单平均涨跌计算RSI，低于30时列入观察。超卖可能持续。',
                      origin='coo-moon/quanti · RSIOversoldScreener（MIT）'),
    'macd': dict(name='MACD · 金叉确认', min_history=35,
                 description='ta库MACD(12,26,9)：最近一期DIF上穿信号线，且收盘高于MA20。',
                 origin='bukosabino/ta 0.11.0（MIT）+ 本地组合条件'),
    'breakout': dict(name='价格 · 20日突破', min_history=21,
                    description='收盘超过此前20期最高收盘，成交额比前20期均额至少1.2。是收盘突破，不是最高价突破。',
                    origin='本地规则；指标展示使用bukosabino/ta'),
}


def load_groups(path, source, day=None):
    with connect(path) as db:
        latest = db.execute('SELECT MAX(day) FROM bars WHERE source=?', (source,)).fetchone()[0]
        selected = day or latest
        rows = db.execute('SELECT * FROM bars WHERE source=? AND day<=? ORDER BY code,day',
                          (source, selected or '')).fetchall()
    groups = defaultdict(list)
    for row in rows:
        groups[row['code']].append(dict(row))
    return selected, groups


def technical_series(rows):
    close = pd.Series([r['close'] for r in rows], dtype=float)
    macd = MACD(close)
    bands = BollingerBands(close)
    columns = {f'ma{n}': SMAIndicator(close, window=n).sma_indicator() for n in (5, 20, 60)}
    columns.update(rsi=RSIIndicator(close).rsi(), dif=macd.macd(), dea=macd.macd_signal(),
                   histogram=macd.macd_diff(), upper=bands.bollinger_hband(), lower=bands.bollinger_lband())
    result = []
    for i, row in enumerate(rows):
        metrics = {key: round(float(values.iloc[i]), 5) if isfinite(values.iloc[i]) else None
                   for key, values in columns.items()}
        result.append(dict(day=row['day'], close=row['close'], amount=row['amount'], **metrics))
    return result


def engine_score(rows, engine):
    if len(rows) < ENGINES[engine]['min_history']:
        return 0, '历史不足'
    if engine in ('quanti_ma', 'quanti_rsi'):
        scorer = MATrendScreener() if engine == 'quanti_ma' else RSIOversoldScreener()
        scorer.init({})
        return round(100 * scorer.screen(rows[-1]['code'], [BarData(r['close']) for r in rows]), 2), None
    if engine == 'breakout':
        prior = rows[-21:-1]
        base = mean(r['amount'] for r in prior)
        ratio = rows[-1]['amount'] / base if base > 0 else 0
        high = max(r['close'] for r in prior)
        if rows[-1]['close'] <= high or ratio < 1.2:
            return 0, None
        return round(min(100, 50 + (rows[-1]['close']/high-1)*1000), 2), None
    metrics = technical_series(rows)
    last, previous = metrics[-1], metrics[-2]
    if previous['histogram'] is None or last['histogram'] is None:
        return 0, '历史不足'
    matched = previous['histogram'] <= 0 < last['histogram'] and last['close'] > last['ma20']
    return (100 if matched else 0), None


def rank_engines(path, source, engine, day=None):
    selected, groups = load_groups(path, source, day)
    items, rejected = [], defaultdict(int)
    for code, rows in groups.items():
        last = rows[-1]
        reason = ('当日无行情' if last['day'] != selected else
                  'ST或停牌' if last['is_st'] == 1 or last['suspended'] == 1 or 'ST' in last['name'].upper() or '退' in last['name'] else
                  '行情无效' if any(not isfinite(r['close']) or r['close'] <= 0 for r in rows) else None)
        if reason:
            rejected[reason] += 1
            continue
        score, reason = engine_score(rows, engine)
        if reason or score <= 0:
            rejected[reason or '未满足算法条件'] += 1
            continue
        metric = technical_series(rows)[-1]
        items.append(dict(code=code, name=last['name'], score=score,
                          verified=last['is_st'] == 0 and last['suspended'] == 0,
                          change_pct=round((last['close']/rows[-2]['close']-1)*100, 2), **metric))
    return dict(day=selected, engine=engine, algorithm=ENGINES[engine], source=source, simulated=source=='demo',
                universe=len(groups), items=sorted(items, key=lambda r: (-r['score'], r['code'])),
                rejections=dict(rejected), note='算法命中强度不是胜率；各算法分数不能互相比。仅对当前缓存池筛选，无收益验证。RSI图表采用ta的Wilder平滑，与Quanti简单平均RSI不同。')
