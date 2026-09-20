"""Small, off-session-safe capability probe; never claims real-time freshness."""
import datetime as dt
import json
from pathlib import Path

from quant.data.connectors.public_market import PublicMarket
from quant.data.realtime_store import atomic_json, raw_packet


def main():
    output = Path('artifacts/realtime/public_probe_' + dt.datetime.now().strftime('%Y%m%dT%H%M%S'))
    output.mkdir(parents=True)
    results = []
    for operation, source, symbol in [('quotes', 'tushare_sina', '000001.SZ'),
        ('quotes', 'akshare_eastmoney', '000001.SZ'),
        ('quotes', 'akshare_eastmoney', '510300.SH'),
        ('bars', 'akshare_eastmoney', '000001.SZ'),
        ('bars', 'akshare_sina', '000001.SZ'),
        ('bars', 'akshare_eastmoney', '510300.SH')]:
        client = PublicMarket(timeout=25)
        result = dict(operation=operation, source=source, symbol=symbol)
        try:
            rows = client.fetch(operation, [symbol], source)
            result.update(rows=len(rows), first=rows[:1], last=rows[-1:])
            raw_packet(Path('data'), operation, rows, dt.datetime.now().astimezone(), source=source)
        except Exception as exc:
            result['error'] = str(exc)
        finally:
            client.close()
        results.append(result)
        atomic_json(output / 'results.json', dict(results=results, trading_session_validated=False))
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
