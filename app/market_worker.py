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
        for code in request['codes']:
            basics = records(bs.query_stock_basic(code=code))
            if not basics or basics[0].get('type') != '1':
                raise RuntimeError(f'{code}不是可识别的股票')
            result = bs.query_history_k_data_plus(
                code, 'date,code,close,amount,tradestatus,isST',
                start_date=request['start'], end_date=request['end'], frequency='d', adjustflag='3')
            for item in records(result):
                # Unknown flags fail closed instead of treating ST/suspension as normal.
                if item['isST'] not in ('0', '1') or item['tradestatus'] not in ('0', '1'):
                    raise RuntimeError(f'{code}交易状态缺失')
                rows.append(dict(code=item['code'], name=basics[0]['code_name'], day=item['date'],
                                 close=float(item['close']), amount=float(item['amount'] or 0),
                                 is_st=int(item['isST']), suspended=int(item['tradestatus'] == '0')))
        return rows
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
        result = dict(rows=rows)
    except Exception as exc:
        result = dict(error=str(exc))
    sys.stdout.write(json.dumps(result, ensure_ascii=True, allow_nan=False))


if __name__ == '__main__':
    main()
