import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.data import update_instruments


def _epoch(day: dt.date) -> int:
    return int(dt.datetime.combine(day, dt.time(), tzinfo=dt.timezone.utc).timestamp() * 1000)


class _FakeHkex:
    source = "hkex"

    def fetch_etp_instruments(
        self, *, target_symbols: tuple[str, ...], as_of: dt.date
    ) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "_request_symbol": list(target_symbols),
                "symbol": [symbol[:5] for symbol in target_symbols],
                "trade_date": [_epoch(as_of)] * len(target_symbols),
                "first_trade_date": [_epoch(dt.date(1999, 11, 12))]
                * len(target_symbols),
                "lot_size": [500] * len(target_symbols),
                "name": ["ETF"] * len(target_symbols),
                "currency": ["HKD"] * len(target_symbols),
                "product_sub_category": ["ETFs"] * len(target_symbols),
            }
        )


@pytest.mark.parametrize(
    "argv, code",
    [
        (
            ["--source", "hkex-etp", "--market", "SH", "--as-of", "2026-07-10", "--symbols", "02800.HK"],
            "HKEX_ETP_TARGETS_INVALID",
        ),
        (
            ["--source", "hkex-etp", "--market", "HK", "--symbols", "02800.HK"],
            "HKEX_ETP_TARGETS_INVALID",
        ),
        (
            ["--source", "hkex-etp", "--market", "HK", "--as-of", "2026-07-10"],
            "HKEX_ETP_TARGETS_INVALID",
        ),
        (
            ["--source", "tushare", "--market", "HK", "--as-of", "2026-07-10"],
            "HKEX_ETP_TARGETS_INVALID",
        ),
        (
            ["--source", "hkex-notice", "--market", "HK", "--as-of", "2026-07-10", "--symbols", "02983.HK"],
            "HK_TEMPORARY_NOTICE_INVALID",
        ),
    ],
)
def test_invalid_hkex_arguments_fail_before_connector(
    argv: list[str], code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden() -> None:
        raise AssertionError("connector must not be constructed")

    monkeypatch.setattr(update_instruments, "HkexEtpConnector", forbidden)
    with pytest.raises(ValueError, match=f"^{code}$"):
        update_instruments.main(argv)


def test_hkex_cli_writes_expected_json_without_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(update_instruments, "HkexEtpConnector", _FakeHkex)
    code = update_instruments.main(
        [
            "--source",
            "hkex-etp",
            "--market",
            "HK",
            "--as-of",
            "2026-07-10",
            "--symbols",
            "03489.HK",
            "02800.HK",
            "--data-root",
            str(tmp_path),
        ]
    )
    output = capsys.readouterr().out
    assert code == 0
    assert '"clean_rows": 2' in output
    assert "token" not in output.lower()


def test_hkex_notice_cli_projects_02983(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = update_instruments.main(
        [
            "--source",
            "hkex-notice",
            "--market",
            "HK",
            "--as-of",
            "2026-07-10",
            "--symbols",
            "02983.HK",
            "--notice-config",
            "configs/instruments/hk_temporary_counters_2026.toml",
            "--data-root",
            str(tmp_path),
        ]
    )
    assert code == 0
    assert '"clean_rows": 1' in capsys.readouterr().out
    clean = pl.read_parquet(
        tmp_path / "clean" / "instrument" / "market=HK" / "data.parquet"
    )
    assert clean.row(0, named=True)["symbol"] == "02983.HK"
    assert clean.row(0, named=True)["board_lot"] == 160
