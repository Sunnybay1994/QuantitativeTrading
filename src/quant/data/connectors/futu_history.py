"""Read-only Futu history access; SDK stays in the connectors package."""

from typing import Any


def open_quotes() -> Any:
    import futu  # type: ignore[import-untyped]

    return futu.OpenQuoteContext(host="127.0.0.1", port=11111)


def history_page(context: Any, symbol: str, start: str, end: str,
                 page_key: bytes | None = None) -> tuple[Any, bytes | None]:
    import futu

    code, market = symbol.split(".")
    ret, frame, next_key = context.request_history_kline(
        f"{market}.{code}", start=start, end=end, ktype=futu.KLType.K_1M,
        autype=futu.AuType.NONE, max_count=1000, page_req_key=page_key,
    )
    if ret != futu.RET_OK:
        raise RuntimeError(str(frame))
    return frame, next_key


def history_quota(context: Any) -> tuple[int, int, set[str]]:
    import futu

    ret, data = context.get_history_kl_quota(get_detail=True)
    if ret != futu.RET_OK:
        raise RuntimeError(str(data))
    used, remaining, details = data
    codes = set()
    for item in details:
        market, code = item["code"].split(".")
        codes.add(f"{code}.{market}")
    return int(used), int(remaining), codes
