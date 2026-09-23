"""Isolated SDK calls: bounded lifetime, existing credentials, no trading APIs."""

import contextlib
import datetime as dt
import io
import multiprocessing as mp
from typing import Any
from unittest.mock import patch


def _call(operation: str, symbols: list[str], source: str) -> list[dict]:
    if operation == 'baostock_catalog':
        from quant.data.connectors.baostock import BaostockConnector
        return BaostockConnector().fetch_instruments('SH').to_dicts()
    import requests

    captured = []
    request = requests.sessions.Session.request

    def bounded(session, method, url, **kwargs):
        kwargs['timeout'] = (3, 6)
        # Preserve the upstream timestamp which AKShare's tabular projection drops.
        if 'qt/stock/get' in url and len(symbols) == 1:
            params = dict(kwargs.get('params') or {})
            code, market = symbols[0].split('.')
            params['secid'] = f'{1 if market == "SH" else 0}.{code}'
            params['fields'] = params.get('fields', '') + ',f86'
            kwargs['params'] = params
        response = request(session, method, url, **kwargs)
        response.raise_for_status()
        if 'qt/stock/get' in url:
            captured.append(response.json()['data'])
        return response

    with patch.object(requests.sessions.Session, 'request', bounded):
        if operation == 'universe':
            import tushare as ts  # type: ignore[import-untyped]
            from quant.settings import load_tushare_settings
            pro = ts.pro_api(load_tushare_settings().token, timeout=10)
            stocks = pro.stock_basic(list_status='L', fields='ts_code,name,list_date')
            funds = pro.fund_basic(market='E', status='L', fields='ts_code,name,list_date')
            return ([dict(symbol=r['ts_code'], name=r['name'], list_date=r['list_date'], asset='stock')
                     for r in stocks.to_dict('records')]
                    + [dict(symbol=r['ts_code'], name=r['name'], list_date=r['list_date'], asset='etf')
                       for r in funds.to_dict('records') if 'ETF' in str(r['name']).upper()])
        if source == 'tushare_sina':
            import tushare as ts
            from quant.settings import load_tushare_settings
            token = load_tushare_settings().token
            # Supply the existing token in memory; still execute the SDK permission check.
            with patch('tushare.util.verify_token.get_token', return_value=token):
                frame = ts.realtime_quote(ts_code=','.join(symbols), src='sina')
            if frame is None:
                raise ValueError('Empty Tushare quote')
            rows = []
            for r in frame.to_dict('records'):
                code, market = r['TS_CODE'].split('.')
                day = dt.datetime.strptime(str(r['DATE']), '%Y%m%d').date()
                rows.append(dict(code=f'{market}.{code}', data_date=str(day),
                    data_time=str(r['TIME']), last_price=r['PRICE'], volume=r['VOLUME'],
                    turnover=r['AMOUNT'], suspension=float(r['PRICE']) <= 0, source=source))
            return rows
        import akshare as ak  # type: ignore[import-untyped]
        symbol = symbols[0]
        code, market = symbol.split('.')
        if operation == 'quotes':
            ak.stock_bid_ask_em(symbol=code)
            data = captured[-1]
            if str(data['f57']) != code:
                raise ValueError('Unexpected Eastmoney symbol')
            stamp = dt.datetime.fromtimestamp(float(data['f86']), dt.timezone(dt.timedelta(hours=8)))
            return [dict(code=f'{market}.{code}', data_date=str(stamp.date()),
                data_time=str(stamp.time()), last_price=data['f43'], volume=float(data['f47']) * 100,
                turnover=data['f48'], suspension=float(data['f43']) <= 0,
                source='akshare_eastmoney', upstream_time_field='f86')]
        if source == 'akshare_sina':
            frame = ak.stock_zh_a_minute(symbol=market.lower() + code, period='1', adjust='')
            return [dict(code=f'{market}.{code}', time_key=str(r['day']),
                **{k: float(r[k]) for k in ('open', 'high', 'low', 'close', 'volume')},
                turnover=None, source=source) for r in frame.to_dict('records')]
        fn = ak.fund_etf_hist_min_em if code.startswith(('5', '15', '16')) else ak.stock_zh_a_hist_min_em
        frame = fn(symbol=code, period='1', adjust='')
        return [dict(code=f'{market}.{code}', time_key=str(r['时间']),
            open=float(r['开盘']), high=float(r['最高']), low=float(r['最低']), close=float(r['收盘']),
            volume=float(r['成交量']) * 100, turnover=float(r['成交额']),
            source='akshare_eastmoney') for r in frame.to_dict('records')]


def _worker(pipe):
    try:
        while True:
            args = pipe.recv()
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    result = _call(*args)
                pipe.send({'rows': result})
            except Exception as exc:
                # SDK exceptions can embed authenticated URLs. Never persist their text.
                pipe.send({'error': type(exc).__name__})
    except (EOFError, BrokenPipeError):
        pass
    finally:
        pipe.close()


class PublicMarket:
    def __init__(self, timeout: float = 12):
        self.timeout = timeout
        self.process: Any = None
        self.pipe: Any = None

    def fetch(self, operation: str, symbols: list[str], source: str) -> list[dict]:
        if self.process is None:
            ctx = mp.get_context('spawn')
            self.pipe, child = ctx.Pipe()
            self.process = ctx.Process(target=_worker, args=(child,), daemon=True)
            self.process.start()
            child.close()
        try:
            self.pipe.send((operation, symbols, source))
            if not self.pipe.poll(self.timeout):
                raise TimeoutError(f'{source} exceeded request deadline')
            result = self.pipe.recv()
        except (OSError, EOFError, TimeoutError):
            self.close()
            raise
        if 'error' in result:
            raise RuntimeError(f'{source}: {result["error"]}')
        return result['rows']

    def close(self):
        if self.process is not None:
            self.process.terminate()
            self.process.join(timeout=2)
            self.pipe.close()
            self.process = self.pipe = None
