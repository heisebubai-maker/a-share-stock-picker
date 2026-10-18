"""Forward signal study on cached histories; deliberately not a portfolio backtest."""
from collections import defaultdict
from statistics import mean
from .storage import connect
from .strategy_lab import assess


def study(path, source, config, horizon=5, cost_pct=.3):
    with connect(path) as db:
        rows=[dict(r) for r in db.execute('''SELECT b.*,c.pe FROM bars b LEFT JOIN context c
          ON b.source=c.source AND b.code=c.code AND b.day=c.day WHERE b.source=? ORDER BY b.code,b.day''',(source,))]
    groups=defaultdict(list)
    for row in rows: groups[row['code']].append(row)
    samples=[]
    for code,series in groups.items():
        # Non-overlapping within each stock; signals at t enter at t+1 close.
        for i in range(config.min_history-1,len(series)-horizon-1,horizon+1):
            signal,_=assess(series[:i+1],config)
            if not signal: continue
            entry,exit_row=series[i+1],series[i+1+horizon]
            outcome=(exit_row['close']/entry['close']-1)*100-cost_pct
            samples.append(dict(code=code,signal_day=series[i]['day'],entry_day=entry['day'],exit_day=exit_row['day'],return_pct=round(outcome,3)))
    values=[s['return_pct'] for s in samples]
    return dict(strategy=config.model_dump(),horizon=horizon,cost_pct=cost_pct,count=len(samples),
                mean_pct=round(mean(values),3) if values else None,
                win_rate=round(sum(v>0 for v in values)/len(values)*100,2) if values else None,
                worst_pct=min(values) if values else None,samples=samples[-100:],
                note='历史信号检验，非组合回测：仅使用当前缓存股票池，存在幸存者及选池偏差；每股样本不重叠，跨股可能重叠。信号次日收盘入场，固定持有后收盘退出，扣除双边费用与滑点假设；未模拟涨跌停、停牌成交、分红除权和仓位。不能据此判断策略可盈利。')
