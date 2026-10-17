"""SDK worker: stdout is one JSON document, SDK chatter is discarded."""
import contextlib
import io
import json
import sys


def records(result):
    if result.error_code != '0':
        raise RuntimeError(f'BaoStock错误 {result.error_code}: {result.error_msg}')
    rows = []
    while result.next():
        rows.append(dict(zip(result.fields, result.get_row_data())))
    if result.error_code != '0':
        raise RuntimeError(f'BaoStock分页错误 {result.error_code}')
    return rows


def fetch(bs, request):
    login = bs.login()
    if login.error_code != '0':
        raise RuntimeError(f'BaoStock登录失败 {login.error_code}: {login.error_msg}')
    try:
        rows = []
        sectors={}
        if request.get('include_context'):
            # Industry is an as-downloaded snapshot, not point-in-time historical classification.
            try:
                sectors={r['code']:r['industry'] for r in records(bs.query_stock_industry())}
            except Exception:
                sectors={}
        for code in request['codes']:
            basics = records(bs.query_stock_basic(code=code))
            if not basics or basics[0].get('type') != '1':
                raise RuntimeError(f'{code}不是可识别的股票')
            result = bs.query_history_k_data_plus(
                code, 'date,code,close,amount,tradestatus,isST'+(',peTTM,pbMRQ' if request.get('include_context') else ''),
                start_date=request['start'], end_date=request['end'], frequency='d', adjustflag='3')
            for item in records(result):
                # Unknown flags fail closed instead of treating ST/suspension as normal.
                if item['isST'] not in ('0', '1') or item['tradestatus'] not in ('0', '1'):
                    raise RuntimeError(f'{code}交易状态缺失')
                rows.append(dict(code=item['code'], name=basics[0]['code_name'], day=item['date'],
                                 close=float(item['close']), amount=float(item['amount'] or 0),
                                 is_st=int(item['isST']), suspended=int(item['tradestatus'] == '0')))
                if request.get('include_context'):
                    rows[-1]['sector']=sectors.get(code)
                    rows[-1]['pe']=float(item['peTTM']) if item.get('peTTM') else None
                    rows[-1]['pb']=float(item['pbMRQ']) if item.get('pbMRQ') else None
        if not request.get('include_context'):
            return rows
        indices=[]
        for code in ('sh.000001','sh.000300','sz.399006'):
            for item in records(bs.query_history_k_data_plus(code,'date,code,close',
                    start_date=request['start'],end_date=request['end'],frequency='d',adjustflag='3')):
                indices.append(dict(code=item['code'],day=item['date'],close=float(item['close'])))
        return dict(rows=rows,benchmarks=indices)
    finally:
        bs.logout()


def main():
    try:
        request = json.loads(sys.stdin.read())
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                import baostock as bs
            except ImportError as exc:
                raise RuntimeError('缺少baostock依赖，请重新运行启动脚本安装requirements.txt') from exc
            rows = fetch(bs, request)
        result = rows if isinstance(rows,dict) else dict(rows=rows)
    except Exception as exc:
        result = dict(error=str(exc))
    sys.stdout.write(json.dumps(result, ensure_ascii=True, allow_nan=False))


if __name__ == '__main__':
    main()
