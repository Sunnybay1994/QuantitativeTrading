import datetime as dt
import hashlib
import io
from pathlib import Path

import polars as pl
import pytest

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # type: ignore[import-not-found]  # noqa: E402

from quant.gui.launcher import ARTIFACT_ROOT_ENV  # noqa: E402
from quant.research.lightweight_run import (  # noqa: E402
    LightweightResearchRunV1,
    ResearchFoldV1,
    ResearchInputDigestV1,
    publish_lightweight_research_run,
)


def _app_path() -> Path:
    return Path(__file__).parents[2] / "src" / "quant" / "gui" / "app.py"


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _publish_fixture(tmp_path: Path) -> Path:
    buffer = io.BytesIO()
    pl.DataFrame(
        {
            "strategy": ["fixture", "fixture"],
            "date": [dt.date(2026, 7, 8), dt.date(2026, 7, 9)],
            "unit_nav": [1.0, 1.01],
            "fold": [1, 1],
            "cost_multiplier": [1.0, 1.0],
        }
    ).write_parquet(buffer)
    run = LightweightResearchRunV1(
        schema_version="lightweight-research-run-v1",
        run_id="",
        hypothesis_id="gui-app-fixture",
        hypothesis="The default cockpit should expose immutable evidence clearly.",
        strategy_name="fixture",
        strategy_version="1.0.0",
        conclusion="RESEARCH_ONLY",
        random_seed=0,
        config_relative_path="configs/research/gui.toml",
        config_sha256=_digest(b"config"),
        code_sha256=_digest(b"code"),
        universe_name="GUI_APP_FIXTURE",
        universe_frozen_as_of=dt.date(2026, 7, 7),
        candidate_symbols=("510300.SH",),
        data_start=dt.date(2025, 1, 1),
        data_end=dt.date(2026, 7, 9),
        signal_timing="close",
        execution_timing="next_session_open",
        valuation_timing="close",
        folds=(
            ResearchFoldV1(
                1,
                dt.date(2025, 1, 1),
                dt.date(2025, 6, 30),
                dt.date(2025, 7, 1),
                dt.date(2025, 9, 30),
                dt.date(2025, 10, 1),
                dt.date(2026, 7, 9),
            ),
        ),
        cost_multipliers=(0.5, 1.0, 2.0),
        selection_metric="net_sharpe",
        inputs=(
            ResearchInputDigestV1(
                "prices",
                2,
                dt.date(2026, 7, 8),
                dt.date(2026, 7, 9),
                _digest(b"prices"),
            ),
        ),
        outputs=(),
        aggregate_metrics=(("net_sharpe", 0.75),),
        caveats=("Research-only fixture.",),
    )
    artifact_root = tmp_path / "artifacts"
    publish_lightweight_research_run(
        artifact_root=artifact_root,
        run=run,
        output_payloads={"report.json": b"{}", "test_nav.parquet": buffer.getvalue()},
    )
    return artifact_root


def test_default_empty_state_is_safe_and_explains_the_source_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(tmp_path / "missing-artifacts"))

    app = AppTest.from_file(str(_app_path())).run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "Quant 投研工作台"
    assert any("只读研究驾驶舱" in caption.value for caption in app.caption)
    assert any("RUNS_ROOT_MISSING" in str(dataframe.value) for dataframe in app.dataframe)


def test_detail_integrity_action_renders_verified_nav_without_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(_publish_fixture(tmp_path)))
    app = AppTest.from_file(str(_app_path())).run(timeout=10)
    assert not app.exception
    assert app.metric[0].value == "1"

    app.sidebar.radio[0].set_value("运行详情").run(timeout=10)
    assert not app.exception
    app.button[0].click().run(timeout=10)

    assert not app.exception
    assert any("输出完整性已验证" in message.value for message in app.success)
