"""Explicitly labelled local CSV. Validate whole batch before replacing cache."""
import csv
import io
from datetime import date
from math import isfinite
from .market import normalize_codes, china_today


def parse_csv(text):
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    required = {'code', 'name', 'day', 'close', 'amount'}
    if not required <= set(reader.fieldnames or []):
        raise ValueError('CSV必须包含code,name,day,close,amount；成交额单位为元，价格为不复权收盘价')
    rows, keys, codes = [], set(), set()
    for number, raw in enumerate(reader, 2):
        if len(rows) >= 20000:
            raise ValueError('每次最多20000行')
        try:
            code = normalize_codes([raw['code']])[0]
            day = date.fromisoformat(raw['day'].strip())
            close, amount = float(raw['close']), float(raw['amount'])
            if not isfinite(close) or not isfinite(amount) or close <= 0 or amount < 0:
                raise ValueError('价格必须为正，成交额不能为负，不能有非有限值')
            if day >= china_today():
                raise ValueError('仅允许早于今天的已收盘日线')
            if (code, day) in keys:
                raise ValueError('存在重复代码日期')
            name = raw['name'].strip()
            if not name or len(name) > 80:
                raise ValueError('名称为空或过长')
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f'CSV第{number}行：{exc}') from exc
        keys.add((code, day)); codes.add(code)
        rows.append(dict(code=code, name=name, day=day.isoformat(), close=close, amount=amount,
                         is_st=-1, suspended=-1))
    if not rows or len(codes) > 50:
        raise ValueError('CSV需包含1至50只股票且至少一行数据')
    rows.sort(key=lambda r: (r['code'], r['day']))
    start, end = min(r['day'] for r in rows), max(r['day'] for r in rows)
    if (date.fromisoformat(end)-date.fromisoformat(start)).days > 370:
        raise ValueError('历史范围最多370天')
    return rows, sorted(codes), date.fromisoformat(start), date.fromisoformat(end)
