"""Configurable, explainable screening. Indicators use bukosabino/ta (MIT)."""
import json
from math import isfinite
from statistics import mean, pstdev
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ta.momentum import ROCIndicator
from ta.trend import SMAIndicator

from .storage import connect


class StrategyConfig(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    name: str = Field(default='趋势动量', min_length=1, max_length=40)
    mode: Literal['momentum', 'breakout', 'pullback', 'value'] = 'momentum'
    board: Literal['all', 'main', 'growth'] = 'all'
    min_score: float = Field(default=60, ge=0, le=100)
    min_amount: float = Field(default=1, ge=.1, le=1000)
    min_momentum: float = Field(default=0, ge=-90, le=300)
    max_momentum: float = Field(default=50, ge=-90, le=500)
    max_daily_change: float = Field(default=7, ge=0, le=30)
    max_volatility: float = Field(default=8, gt=0, le=30)
    max_cap: float = Field(default=2000, gt=0, le=100000)
    max_pe: float = Field(default=40, gt=0, le=500)
    min_history: int = Field(default=60, ge=21, le=120)
    top_k: int = Field(default=8, ge=1, le=20)
    sector_limit: int = Field(default=3, ge=1, le=20)
    momentum_weight: float = Field(default=40, ge=0, le=100)
    trend_weight: float = Field(default=30, ge=0, le=100)
    stability_weight: float = Field(default=10, ge=0, le=100)
    liquidity_weight: float = Field(default=20, ge=0, le=100)
    allow_unverified: bool = True

    @model_validator(mode='after')
    def valid(self):
        if self.min_momentum > self.max_momentum:
            raise ValueError('涨幅下限不能超过上限')
        if sum(getattr(self, k+'_weight') for k in ('momentum','trend','stability','liquidity')) <= 0:
            raise ValueError('至少一个评分权重大于0')
        return self


PRESETS = {
    'momentum': StrategyConfig().model_dump(),
    'breakout': StrategyConfig(name='放量突破', mode='breakout', min_momentum=3, momentum_weight=30, trend_weight=40).model_dump(),
    'pullback': StrategyConfig(name='强势回调', mode='pullback', min_momentum=3, max_momentum=35, min_score=50).model_dump(),
    'value': StrategyConfig(name='估值趋势', mode='value', max_pe=25, max_cap=100000, momentum_weight=20, stability_weight=30).model_dump(),
}


def load_strategy(path):
    with connect(path) as db:
        row=db.execute('SELECT payload FROM strategy_profiles WHERE active=1').fetchone()
    return StrategyConfig(**json.loads(row[0])) if row else StrategyConfig()


def board_matches(code, board):
    growth=code.startswith(('sz.30','sh.688','sh.689'))
    return board=='all' or (board=='growth' and growth) or (board=='main' and not growth)


def assess(rows, config):
    """Return result/rejection reason, using only supplied bars through the as-of day."""
    if len(rows)<config.min_history: return None,'历史不足'
    last=rows[-1]
    if not board_matches(last['code'],config.board): return None,'板块范围'
    if last['is_st']==1 or last['suspended']==1 or 'ST' in last['name'].upper() or '退' in last['name']:
        return None,'ST或停牌'
    verified=last['is_st']==0 and last['suspended']==0
    if not verified and not config.allow_unverified: return None,'交易状态未核验'
    prices=[r['close'] for r in rows]
    amounts=[r['amount'] for r in rows[-20:]]
    if any(not isfinite(x) or x<=0 for x in prices) or any(not isfinite(x) or x<0 for x in amounts):
        return None,'行情无效'
    amount=mean(amounts)
    if amount<config.min_amount*1e8: return None,'成交额不足'
    series=pd.Series(prices,dtype=float)
    momentum=float(ROCIndicator(series,window=20).roc().iloc[-1])
    ma20=float(SMAIndicator(series,window=20).sma_indicator().iloc[-1])
    if (prices[-1]/prices[-2]-1)*100>config.max_daily_change: return None,'单日涨幅过大'
    volatility=pstdev([(b/a-1)*100 for a,b in zip(prices[-21:-1],prices[-20:])])
    if not config.min_momentum<=momentum<=config.max_momentum: return None,'20日涨幅范围'
    if volatility>config.max_volatility: return None,'波动过大'
    if prices[-1]<ma20: return None,'低于20日均线'
    ratio=amounts[-1]/mean(amounts[:-1]) if mean(amounts[:-1])>0 else 0
    if config.mode=='breakout' and (prices[-1]<=max(prices[-21:-1]) or ratio<1.2): return None,'未放量突破'
    if config.mode=='pullback' and not (prices[-1]<max(prices[-10:]) and 0<=(prices[-1]/ma20-1)*100<=3): return None,'未回调至均线附近'
    if config.mode=='value' and (last.get('pe') is None or not 0<last['pe']<=config.max_pe): return None,'估值缺失或超限'
    clamp=lambda v:max(0,min(1,v))
    raw=dict(momentum=clamp((momentum+10)/30),trend=clamp(((prices[-1]/ma20-1)*100+5)/15),
             stability=clamp(1-volatility/config.max_volatility),liquidity=clamp(amount/(config.min_amount*5e8)))
    total=sum(getattr(config,k+'_weight') for k in raw)
    factors={k:round(v*getattr(config,k+'_weight')/total*100,2) for k,v in raw.items()}
    score=round(sum(factors.values()),2)
    if score<config.min_score: return None,'评分不足'
    return dict(code=last['code'],name=last['name'],close=prices[-1],score=score,factors=factors,
                momentum_pct=round(momentum,2),volatility_pct=round(volatility,2),
                amount_ratio=round(ratio,2),verified=verified),None
