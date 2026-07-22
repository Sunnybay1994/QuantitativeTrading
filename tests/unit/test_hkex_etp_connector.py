import datetime as dt

import httpx
import pytest

from quant.data.connectors.hkex_etp import HkexEtpConnector


def test_public_website_connector_requires_license_without_network_access() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise AssertionError("disabled connector must not access the network")

    connector = HkexEtpConnector(
        httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(ValueError, match="^HKEX_ETP_LICENSE_REQUIRED$"):
        connector.fetch_etp_instruments(
            target_symbols=("02800.HK",), as_of=dt.date(2026, 7, 10)
        )
    assert calls == []


@pytest.mark.parametrize(
    "symbols",
    [(), ("2800.HK",), ("02800.HK", "02800.HK"), ("03033.HK", "02800.HK")],
)
def test_invalid_targets_still_fail_before_license_check(
    symbols: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="^HKEX_ETP_TARGETS_INVALID$"):
        HkexEtpConnector().fetch_etp_instruments(
            target_symbols=symbols, as_of=dt.date(2026, 7, 10)
        )
