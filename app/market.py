"""Bounded, isolated BaoStock downloads; no fabricated fallback."""
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from pathlib import Path

DEFAULT_CODES = ['sh.600000', 'sh.600036', 'sh.600519', 'sh.601318',
                 'sh.601398', 'sh.600900', 'sz.000001', 'sz.000333',
                 'sz.000651', 'sz.002415', 'sz.300059', 'sz.300750']


class DataError(Exception):
    pass


def china_today():
    return datetime.now(timezone(timedelta(hours=8))).date()


def normalize_codes(codes):
    result = []
    for value in codes:
        value = value.strip().lower()
        if re.fullmatch(r'\d{6}', value):
            value = ('sh.' if value.startswith('6') else 'sz.') + value
        if not re.fullmatch(r'(sh\.6\d{5}|sz\.(00|30)\d{4})', value):
            raise ValueError('请输入沪深A股代码，例如600519、000001、sh.600036')
        if value not in result:
            result.append(value)
    if not 1 <= len(result) <= 50:
        raise ValueError('每次同步1至50只股票')
    return result


def validate_rows(rows, codes, start, end):
    if not isinstance(rows, list) or not rows:
        raise DataError('接口未返回日线；缓存未修改，请稍后重试')
    clean, keys = [], set()
    for row in rows:
        try:
            code, day = row['code'], date.fromisoformat(row['day'])
            close, amount = float(row['close']), float(row['amount'])
            if (code not in codes or not start <= day <= end or
                    not isfinite(close) or close <= 0 or not isfinite(amount) or amount < 0 or
                    row['is_st'] not in (0, 1) or row['suspended'] not in (0, 1) or
                    (code, day) in keys):
                raise ValueError('invalid row')
            keys.add((code, day))
            clean.append(dict(code=code, name=str(row['name'])[:80], day=day.isoformat(),
                              close=close, amount=amount, is_st=row['is_st'], suspended=row['suspended']))
        except (KeyError, TypeError, ValueError) as exc:
            raise DataError('接口数据校验失败，缓存未修改') from exc
    if {r['code'] for r in clean} != set(codes):
        raise DataError('部分股票无数据，整批未写入；检查代码或上市日期')
    return clean


def download(codes, start, end, include_context=False):
    codes = normalize_codes(codes)
    if not start <= end < china_today() or (end - start).days > 370:
        raise ValueError('日期范围最多370天，结束日期必须早于今天，避免使用未收盘行情')
    request = json.dumps(dict(codes=codes, start=start.isoformat(), end=end.isoformat(),include_context=include_context))
    last_error = None
    # Each attempt has its own SDK session. Total runtime <= 2 * 90 seconds.
    for attempt in range(2):
        try:
            process = subprocess.run([sys.executable, '-m', 'app.market_worker'],
                                     input=request, capture_output=True, text=True, encoding='utf-8',
                                     timeout=90, cwd=Path(__file__).resolve().parent.parent,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            payload = json.loads(process.stdout)
            if not isinstance(payload, dict):
                raise DataError('下载进程返回格式异常')
            if process.returncode or payload.get('error'):
                raise DataError(payload.get('error', '下载进程异常'))
            cleaned=validate_rows(payload['rows'], codes, start, end)
            if not include_context:
                return cleaned
            original={(r['code'],r['day']):r for r in payload['rows']}
            for row in cleaned:
                detail=original[(row['code'],row['day'])]
                row['sector']=str(detail.get('sector') or '')[:80] or None
                for key in ('pe','pb'):
                    value=detail.get(key)
                    row[key]=float(value) if value is not None and isfinite(float(value)) else None
            benchmarks=[]
            seen=set()
            for row in payload.get('benchmarks',[]):
                key=(row['code'],row['day'])
                if (row['code'] not in ('sh.000001','sh.000300','sz.399006') or key in seen or
                        not start<=date.fromisoformat(row['day'])<=end or
                        not isfinite(float(row['close'])) or float(row['close'])<=0):
                    raise DataError('指数行情校验失败')
                seen.add(key)
                benchmarks.append(dict(code=row['code'],day=row['day'],close=float(row['close'])))
            return dict(rows=cleaned,benchmarks=benchmarks)
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, TypeError, ValueError, DataError) as exc:
            last_error = exc
    raise DataError(f'BaoStock同步失败（已尝试2次）：{last_error}。保留原缓存，不切换模拟数据。')
