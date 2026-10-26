"""Read-only subscribed quotes/current K lines. Never calls historical or trading APIs."""

import socket
from typing import Any


class FutuRealtime:
    def __init__(self, host: str = '127.0.0.1', port: int = 11111):
        import futu

        # Avoid the SDK's unbounded initial connection retry when OpenD is absent.
        with socket.create_connection((host, port), timeout=3):
            pass
        self.sdk = futu
        self.context = futu.OpenQuoteContext(host=host, port=port, is_async_connect=True)
        self.context.set_sync_query_connect_timeout(5)

    def _value(self, result: tuple) -> Any:
        ret, value = result
        if ret != self.sdk.RET_OK:
            raise RuntimeError(str(value))
        return value

    def state(self) -> dict:
        state = self._value(self.context.get_global_state())
        if str(state.get('qot_logined')).lower() not in ('true', '1'):
            raise RuntimeError('OpenD is not logged into the quote server')
        return {k: state.get(k) for k in ('qot_logined', 'market_sh', 'market_sz',
                                         'timestamp', 'local_timestamp')}

    def quota(self) -> dict:
        data = self._value(self.context.query_subscription(is_all_conn=True))
        return {k: data.get(k) for k in ('total_used', 'remain', 'own_used')}

    @staticmethod
    def code(symbol: str) -> str:
        code, market = symbol.split('.')
        return f'{market}.{code}'

    def _codes(self, symbols: list[str]) -> list[str]:
        return [self.code(s) for s in symbols]

    def subscribe_types(self, symbols: list[str], subtypes: list, *, reserve: int | None = None,
                        slots_per_symbol: int | None = None) -> dict:
        """Subscribe exact subtypes. Each (symbol, subtype) uses one quota slot."""
        if not symbols:
            return self.quota()
        slots = slots_per_symbol if slots_per_symbol is not None else len(subtypes)
        quota = self.quota()
        required = len(symbols) * slots
        remain = int(quota['remain'])
        floor = reserve if reserve is not None else 0
        if required + floor > remain:
            raise RuntimeError(f'Subscription quota insufficient: need {required}, '
                               f'reserve {floor}, remaining {remain}')
        self._value(self.context.subscribe(self._codes(symbols), subtypes, subscribe_push=False))
        return self.quota()

    def unsubscribe_types(self, symbols: list[str], subtypes: list) -> dict:
        if not symbols:
            return self.quota()
        self._value(self.context.unsubscribe(self._codes(symbols), subtypes))
        return self.quota()

    def subscribe(self, symbols: list[str], reserve: int) -> dict:
        """Legacy helper: QUOTE+K_1M for every symbol (2 slots each). Prefer quote-first path."""
        return self.subscribe_types(
            symbols, [self.sdk.SubType.QUOTE, self.sdk.SubType.K_1M],
            reserve=reserve, slots_per_symbol=2)

    def subscribe_quotes(self, symbols: list[str], reserve: int) -> dict:
        return self.subscribe_types(symbols, [self.sdk.SubType.QUOTE], reserve=reserve,
                                    slots_per_symbol=1)

    def subscribe_k1m(self, symbols: list[str], *, reserve: int | None = None) -> dict:
        return self.subscribe_types(symbols, [self.sdk.SubType.K_1M], reserve=reserve,
                                    slots_per_symbol=1)

    def unsubscribe_k1m(self, symbols: list[str]) -> dict:
        return self.unsubscribe_types(symbols, [self.sdk.SubType.K_1M])

    def quotes(self, symbols: list[str]) -> list[dict]:
        data = self._value(self.context.get_stock_quote(self._codes(symbols)))
        fields = ['code', 'data_date', 'data_time', 'last_price', 'volume', 'turnover',
                  'suspension', 'sec_status']
        return data[[f for f in fields if f in data.columns]].to_dict('records')

    def bars(self, symbol: str) -> list[dict]:
        data = self._value(self.context.get_cur_kline(self.code(symbol), 1000,
                          ktype=self.sdk.KLType.K_1M, autype=self.sdk.AuType.NONE))
        return data[['code', 'time_key', 'open', 'high', 'low', 'close',
                     'volume', 'turnover']].to_dict('records')

    def close(self) -> None:
        # Only this connection is closed; never unsubscribe other clients.
        self.context.close()
