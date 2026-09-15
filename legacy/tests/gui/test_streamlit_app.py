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


def _publish_fixture(
    tmp_path: Path,
    *,
    count: int = 1,
    mismatched_data_end_index: int | None = None,
    empty_caveat_index: int | None = None,
) -> Path:
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
    artifact_root = tmp_path / "artifacts"
    for index in range(count):
        data_end = (
            dt.date(2026, 7, 10)
            if index == mismatched_data_end_index
            else dt.date(2026, 7, 9)
        )
        run = LightweightResearchRunV1(
            schema_version="lightweight-research-run-v1",
            run_id="",
            hypothesis_id=f"gui-app-fixture-{index + 1}",
            hypothesis="The default cockpit should expose immutable evidence clearly.",
            strategy_name=f"fixture_{index + 1}",
            strategy_version="1.0.0",
            conclusion="RESEARCH_ONLY",
            random_seed=index,
            config_relative_path=f"configs/research/gui_{index + 1}.toml",
            config_sha256=_digest(f"config-{index + 1}".encode()),
            code_sha256=_digest(f"code-{index + 1}".encode()),
            universe_name="GUI_APP_FIXTURE",
            universe_frozen_as_of=dt.date(2026, 7, 7),
            candidate_symbols=("510300.SH",),
            data_start=dt.date(2025, 1, 1),
            data_end=data_end,
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
                    data_end,
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
            aggregate_metrics=(("net_sharpe", 0.75 - index / 10),),
            caveats=(
                () if index == empty_caveat_index else ("Research-only fixture.",)
            ),
        )
        publish_lightweight_research_run(
            artifact_root=artifact_root,
            run=run,
            output_payloads={
                "report.json": b"{}",
                "test_nav.parquet": buffer.getvalue(),
            },
        )
    return artifact_root


def test_default_empty_state_is_safe_and_explains_the_source_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_source = _app_path().read_text(encoding="utf-8")
    assert "use_container_width" not in app_source
    assert app_source.count('width="stretch"') == 13

    monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(tmp_path / "missing-artifacts"))

    app = AppTest.from_file(str(_app_path())).run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "Quant 投研工作台"
    assert any("只读研究驾驶舱" in caption.value for caption in app.caption)
    assert any("RUNS_ROOT_MISSING" in str(dataframe.value) for dataframe in app.dataframe)


def test_overview_default_keeps_catalog_rows_order_and_full_kpi_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = _publish_fixture(tmp_path, count=3)
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(artifact_root))
    expected_strategies = ["fixture_1", "fixture_2", "fixture_3"]

    app = AppTest.from_file(str(_app_path())).run(timeout=10)

    assert not app.exception
    assert app.sidebar.text_input[0].value == ""
    assert app.sidebar.radio[1].value == "ALL"
    assert app.metric[0].value == "3"
    assert app.dataframe[0].value["strategy"].tolist() == expected_strategies
    assert any(
        "当前显示 3 / 3 个运行；顶部卡片统计全部 canonical runs。"
        in caption.value
        for caption in app.caption
    )


def test_overview_search_and_caveat_filters_keep_kpi_catalog_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = _publish_fixture(
        tmp_path,
        count=3,
        empty_caveat_index=2,
    )
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(artifact_root))

    app = AppTest.from_file(str(_app_path())).run(timeout=10)
    app.sidebar.text_input[0].set_value("FIXTURE_2").run(timeout=10)
    assert not app.exception
    assert app.metric[0].value == "3"
    assert app.dataframe[0].value["strategy"].tolist() == ["fixture_2"]
    assert any("当前显示 1 / 3 个运行" in caption.value for caption in app.caption)

    app.sidebar.radio[1].set_value("PRESENT").run(timeout=10)
    assert not app.exception
    assert app.dataframe[0].value["strategy"].tolist() == ["fixture_2"]

    app.sidebar.radio[1].set_value("ABSENT").run(timeout=10)
    assert not app.exception
    assert any("没有可展示的自洽运行" in message.value for message in app.info)

    app.sidebar.text_input[0].set_value("").run(timeout=10)
    assert not app.exception
    assert app.dataframe[0].value["strategy"].tolist() == ["fixture_3"]

    app.sidebar.radio[1].set_value("ALL").run(timeout=10)
    assert not app.exception
    assert app.metric[0].value == "3"
    assert len(app.dataframe[0].value) == 3


def test_overview_combined_filter_has_explicit_empty_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = _publish_fixture(tmp_path, count=2)
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(artifact_root))

    app = AppTest.from_file(str(_app_path())).run(timeout=10)
    app.sidebar.multiselect[0].set_value(["RESEARCH_ONLY"]).run(timeout=10)
    app.sidebar.multiselect[1].set_value(["fixture_1"]).run(timeout=10)
    app.sidebar.text_input[0].set_value("does-not-exist").run(timeout=10)

    assert not app.exception
    assert any("当前显示 0 / 2 个运行" in caption.value for caption in app.caption)
    assert any("没有可展示的自洽运行" in message.value for message in app.info)
    assert len(app.dataframe) == 0


def test_overview_filter_reruns_do_not_call_output_or_nav_verifiers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = _publish_fixture(tmp_path, count=2)
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(artifact_root))

    def fail_on_call(*_: object, **__: object) -> None:
        raise AssertionError("overview filtering must not verify output or NAV")

    for name in (
        "verify_research_run",
        "verify_research_run_comparison",
        "load_nav_projection",
        "load_comparison_nav_projection",
    ):
        monkeypatch.setattr(f"quant.gui.research_runs.{name}", fail_on_call)

    app = AppTest.from_file(str(_app_path())).run(timeout=10)
    app.sidebar.text_input[0].set_value("fixture").run(timeout=10)
    app.sidebar.radio[1].set_value("PRESENT").run(timeout=10)
    app.sidebar.radio[1].set_value("ABSENT").run(timeout=10)

    assert not app.exception


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


def test_comparison_requires_explicit_verification_before_rendering_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = _publish_fixture(tmp_path, count=2)
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(artifact_root))
    selected_ids = sorted(
        path.name for path in (artifact_root / "research" / "runs").iterdir()
    )
    app = AppTest.from_file(str(_app_path())).run(timeout=10)

    app.sidebar.radio[0].set_value("运行比较").run(timeout=10)
    assert not app.exception
    app.multiselect[0].set_value(selected_ids).run(timeout=10)
    assert any("比较证据和 NAV 保持锁定" in message.value for message in app.info)

    app.button[0].click().run(timeout=10)

    assert not app.exception
    assert any(
        "比较口径与输出完整性已验证" in message.value for message in app.success
    )


def test_comparison_contract_mismatch_renders_relation_only_in_selection_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = _publish_fixture(
        tmp_path,
        count=2,
        mismatched_data_end_index=1,
    )
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(artifact_root))
    selected_ids = sorted(
        path.name for path in (artifact_root / "research" / "runs").iterdir()
    )
    app = AppTest.from_file(str(_app_path())).run(timeout=10)

    app.sidebar.radio[0].set_value("运行比较").run(timeout=10)
    app.multiselect[0].set_value(selected_ids).run(timeout=10)
    app.button[0].click().run(timeout=10)

    assert not app.exception
    assert any(
        "COMPARISON_CONTRACT_MISMATCH" in message.value for message in app.error
    )
    assert not app.success
    assert len(app.dataframe) == 1
    relation_frame = app.dataframe[0].value
    assert list(relation_frame.columns) == [
        "field",
        f"Run 1 · {selected_ids[0][:12]}",
        f"Run 2 · {selected_ids[1][:12]}",
    ]
    assert relation_frame["field"].tolist() == ["data_end", "folds"]
    assert relation_frame.iloc[:, 1].tolist() == ["REFERENCE", "REFERENCE"]
    assert relation_frame.iloc[:, 2].tolist() == ["DIFFERENT", "DIFFERENT"]
    assert any(
        "REFERENCE 仅表示用户本次选择顺序中的第一项" in caption.value
        for caption in app.caption
    )


def test_output_failure_does_not_render_contract_diagnosis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = _publish_fixture(tmp_path, count=2)
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(artifact_root))
    selected_ids = sorted(
        path.name for path in (artifact_root / "research" / "runs").iterdir()
    )
    (artifact_root / "research" / "runs" / selected_ids[1] / "report.json").write_bytes(
        b"tampered"
    )
    app = AppTest.from_file(str(_app_path())).run(timeout=10)

    app.sidebar.radio[0].set_value("运行比较").run(timeout=10)
    app.multiselect[0].set_value(selected_ids).run(timeout=10)
    app.button[0].click().run(timeout=10)

    assert not app.exception
    assert any("COMPARISON_RUN_UNVERIFIED" in message.value for message in app.error)
    assert not app.success
    assert len(app.dataframe) == 0
    assert not any(
        "严格比较口径诊断" in str(markdown.value) for markdown in app.markdown
    )
