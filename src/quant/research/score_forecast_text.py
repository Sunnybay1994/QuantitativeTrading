"""Score P7 forecast reasons through DeepSeek; default is offline cost planning."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import time
import tomllib
from typing import Annotated, Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from quant.data.connectors.deepseek import DeepSeekClient, RequestFailure, load_key
from quant.data.forecast_text_scores import ScoreCache, publish_panels, read_corpus, write_scores
from quant.factors.forecast_text_score import (
    DIMENSIONS, PROMPT, PROMPT_VERSION, input_token_bound, parse_score, score_key,
)
from quant.research.lightweight_run import dataframe_input_digest
from quant.research.deepseek_batch_window import request_window


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str
    model_epoch: str
    pricing_checked: dt.date
    input_usd_per_million: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    output_usd_per_million: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    max_tokens: Annotated[int, Field(ge=256, le=4096)] = 768
    max_input_bytes: Annotated[int, Field(ge=100, le=100000)] = 24000
    max_attempts: Annotated[int, Field(ge=1, le=3)] = 2
    timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 60.0
    retry_delay_seconds: Annotated[float, Field(ge=0, le=30)] = 2.0


def load_settings(path: Path) -> dict:
    settings = Settings.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
    if settings.model not in {"deepseek-flash", "deepseek-v4-pro"} or not settings.model_epoch.strip():
        raise ValueError("Set a documented DeepSeek model and explicit model_epoch")
    return settings.model_dump()


def load_design(path: Path) -> dict:
    design = tomllib.loads(path.read_text(encoding="utf-8"))
    if (design["scoring"]["prompt_version"] != PROMPT_VERSION
            or design["scoring"]["score_values"] != [0, 1, 2, 3]
            or [s["id"] for s in design["signals"]] != [f"text_{d}" for d in DIMENSIONS]
            or [s["direction"] for s in design["signals"]] != [1, -1, -1]
            or design["availability"] != "own_publication_date_after_close"
            or design["maximum_age_calendar_days"] != 120):
        raise ValueError("Unsupported P7 design; update implementation with a new rubric version")
    return design


def cost_for(input_tokens: int, output_tokens: int, settings: dict) -> float:
    return (input_tokens * settings["input_usd_per_million"]
            + output_tokens * settings["output_usd_per_million"]) / 1_000_000


def validated_usage(response: dict) -> tuple[str, dict]:
    model = response.get("model")
    usage = response.get("usage")
    if not isinstance(model, str) or not model.strip() or not isinstance(usage, dict):
        raise ValueError("Missing model/usage")
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if type(usage.get(name)) is not int or usage[name] < 0:
            raise ValueError("Invalid token usage")
    if usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]:
        raise ValueError("Inconsistent usage")
    # Preserve only numeric usage fields, never arbitrary provider payloads.
    clean = {k: v for k, v in usage.items() if type(v) is int and v >= 0}
    return model, clean


def response_error_code(exc: Exception) -> str:
    """Keep actionable categories without saving provider text or exception values."""
    if isinstance(exc, json.JSONDecodeError):
        return 'invalid_json'
    if isinstance(exc, ValidationError):
        return 'invalid_output_schema'
    if isinstance(exc, (KeyError, TypeError, IndexError)):
        return 'invalid_completion_envelope'
    return {
        'incomplete completion': 'incomplete_completion',
        'evidence is not an exact input substring': 'evidence_not_verbatim',
        'numeric-only must apply to all dimensions': 'inconsistent_numeric_only',
        'duplicate JSON key': 'duplicate_json_key',
        'non-finite JSON constant': 'nonfinite_json',
        'JSON object required': 'invalid_json_object',
        'Unknown or mismatched factual citation': 'invalid_fact_citation',
        'Numbers belong in exact citations, not generated prose': 'uncited_prose_number',
    }.get(str(exc), 'invalid_output_semantics')


def score_one(reason: str, *, settings: dict, cache: ScoreCache, client: Any,
              max_requests: int, max_usd: float, sleep: Callable[[float], None] = time.sleep,
              request_key: str | None = None, token_bound: int | None = None,
              parse: Callable[[str], dict] | None = None,
              development_test: bool = False) -> dict:
    key = request_key or score_key(reason, settings)
    input_bound = token_bound if token_bound is not None else input_token_bound(reason)
    bound = cost_for(input_bound, settings["max_tokens"], settings)
    for attempt_number in range(settings["max_attempts"]):
        prior = cache.latest(key)
        if prior and prior["state"] != "retryable":
            return prior
        window = request_window()
        if not development_test and not window['allowed']:
            return {'state': 'deferred_off_peak', 'actual_model': None,
                    'next_allowed_at': window['next_allowed_at']}
        attempt = cache.reserve(key, bound, max_requests=max_requests, max_usd=max_usd,
                                max_attempts=settings["max_attempts"])
        if attempt is None:
            return prior or {"state": "budget_exhausted", "actual_model": None}
        try:
            response = client.complete(reason, settings)
        except RequestFailure as exc:
            # Charge/reserve conservatively even for unsuccessful attempts.
            cache.finish(attempt, state="retryable" if exc.retryable else "failed", error=exc.code)
        else:
            try:
                model, usage = validated_usage(response)
            except (ValueError, TypeError):
                cache.finish(attempt, state="failed", error="invalid_model_or_usage")
            else:
                cost = cost_for(usage["prompt_tokens"], usage["completion_tokens"], settings)
                if (usage["prompt_tokens"] > input_bound
                        or usage["completion_tokens"] > settings["max_tokens"] or cost > bound):
                    cache.finish(attempt, state="failed", model=model, usage=usage, cost=cost,
                                 error="usage_exceeds_reservation")
                    raise RuntimeError("Provider usage exceeded reservation; stop and reconcile budget")
                try:
                    choices = response["choices"]
                    if len(choices) != 1 or choices[0]["finish_reason"] != "stop":
                        raise ValueError("incomplete completion")
                    content = choices[0]["message"]["content"]
                    score = parse(content) if parse else parse_score(content, reason).model_dump()
                except (ValueError, KeyError, TypeError, IndexError) as exc:
                    cache.finish(attempt, state="retryable", model=model, usage=usage, cost=cost,
                                 error=response_error_code(exc))
                else:
                    cache.finish(attempt, state="success", model=model, usage=usage,
                                 cost=cost, scores=score)
        current = cache.latest(key)
        assert current is not None
        if current["state"] != "retryable":
            return current
        if attempt_number + 1 < settings["max_attempts"]:
            sleep(settings["retry_delay_seconds"])
    assert current is not None
    return current


def run_batch(*, source: Path, config: Path, design_path: Path, output: Path,
              cache_path: Path, execute: bool = False, max_requests: int = 0,
              max_usd: float = 0, limit: int | None = None, client: Any = None,
              development_test: bool = False) -> dict:
    settings, design = load_settings(config), load_design(design_path)
    if (type(max_requests) is not int or max_requests < 0 or not math.isfinite(max_usd)
            or max_usd < 0 or (execute and (max_requests < 1 or max_usd <= 0))
            or (limit is not None and (type(limit) is not int or limit < 1))):
        raise ValueError("Live runs require positive finite request/USD caps; limit must be positive")
    if execute and (dt.date.today() - settings["pricing_checked"]).days not in range(8):
        raise ValueError("Recheck official pricing and update config before live requests (7-day limit)")
    frame = read_corpus(source)
    frame = frame.filter(
        frame["publication_date"].is_between(
            design["start"] - dt.timedelta(days=design["maximum_age_calendar_days"]), design["end"])
    )
    if frame.is_empty():
        raise ValueError("No records within design window")
    inputs = asdict(dataframe_input_digest(name="forecast-reasons", frame=frame,
                    sort_by=["symbol", "publication_date", "report_period", "input_id"],
                    date_column="publication_date"))
    records = frame.to_dicts()
    candidates: dict[str, str] = {}
    for row in records:
        reason = row["reason_text"]
        if (reason and not row["same_day_conflict"]
                and len(reason.encode()) <= settings["max_input_bytes"]):
            candidates.setdefault(score_key(reason, settings), reason)
    selected = dict(list(candidates.items())[:limit])
    estimates = [cost_for(input_token_bound(reason), settings["max_tokens"], settings)
                 for reason in selected.values()]
    plan = {"input_rows": frame.height, "eligible_unique_texts": len(candidates),
            "selected_unique_texts": len(selected), "request_bound_including_retries":
            len(selected) * settings["max_attempts"],
            "usd_bound_one_attempt": sum(estimates),
            "usd_bound_including_retries": sum(estimates) * settings["max_attempts"],
            "max_requests": max_requests, "max_usd": max_usd}
    owned_client = execute and client is None
    if owned_client:
        client = DeepSeekClient(load_key(Path.cwd()), timeout=settings["timeout_seconds"])
    output.mkdir(parents=True, exist_ok=False)
    cache = ScoreCache(cache_path) if execute else None
    totals_before = cache.totals() if cache else {"requests": 0, "charged_or_reserved_usd": 0.0}
    result_by_key = {}
    try:
        if cache:
            for key, reason in selected.items():
                result_by_key[key] = score_one(reason, settings=settings, cache=cache, client=client,
                                               max_requests=max_requests, max_usd=max_usd,
                                               development_test=development_test)
        rows = []
        for record in records:
            reason = record["reason_text"]
            row_key = score_key(reason, settings) if reason else None
            result = result_by_key.get(row_key, {}) if row_key is not None else {}
            state = ("same_day_conflict" if record["same_day_conflict"] else
                     "missing_text" if not reason else
                     "input_too_long" if len(reason.encode()) > settings["max_input_bytes"] else
                     "not_selected" if row_key not in selected else
                     "dry_run" if not execute else result.get("state", "failed"))
            scores = json.loads(result["scores_json"]) if state == "success" else {}
            row = {**record, "cache_key": row_key, "result": state,
                   "actual_model": result.get("actual_model"), "prompt_version": PROMPT_VERSION,
                   "evidence_scope": "provided_reason_excerpt"}
            for name in DIMENSIONS:
                item = scores.get(name, {})
                row.update({f"text_{name}": item.get("score"),
                            f"{name}_status": item.get("status", state),
                            f"{name}_evidence": item.get("evidence")})
            rows.append(row)
        write_scores(rows, output / "scores.parquet")
        totals_after = cache.totals() if cache else totals_before
        # Existing lightweight pattern: config + input/output hashes + run.json.
        # No invented backtest folds or trade performance for a text extraction run.
        report = {"run_type": "forecast-text-scoring", "conclusion": "RESEARCH_ONLY",
                  "dry_run": not execute, "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                  "request_schedule": "development_test" if development_test else "off_peak_only",
                  "deferred_until": sorted({item['next_allowed_at'] for item in result_by_key.values()
                                            if item.get('state') == 'deferred_off_peak'}),
                  "source": str(source), "inputs": inputs, "design": design, "scoring": settings,
                  "evidence_scope": "provided_reason_excerpt_not_full_announcement",
                  "prompt_version": PROMPT_VERSION,
                  "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
                  "plan": plan, "summary": dict(Counter(row["result"] for row in rows)),
                  "cache_totals_before": totals_before, "cache_totals_after": totals_after,
                  "requests_this_run": totals_after["requests"] - totals_before["requests"],
                  "cache_path": str(cache_path) if execute else None}
        (output / "scoring.toml").write_bytes(config.read_bytes())
        (output / "design.toml").write_bytes(design_path.read_bytes())
        # Reuse every existing battery threshold; only restrict its start to the frozen P7 window.
        battery = Path(design["battery"]).read_text(encoding="utf-8")
        battery = re.sub(r"^start = [0-9-]+$", f"start = {design['start']}", battery,
                         count=1, flags=re.MULTILINE)
        if tomllib.loads(battery)["start"] != design["start"]:
            raise ValueError("Cannot align battery start with P7 design")
        (output / "battery.toml").write_text(battery, encoding="utf-8")
        (output / "prompt.txt").write_text(PROMPT, encoding="utf-8")
        requests = cache.requests(set(selected)) if cache else []
        (output / "requests.json").write_text(json.dumps(requests, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
        code_root = Path(__file__).resolve().parents[1]
        report["code_sha256"] = {name: hashlib.sha256((code_root / name).read_bytes()).hexdigest()
            for name in ("research/score_forecast_text.py", "factors/forecast_text_score.py",
                         "data/forecast_text_scores.py", "data/connectors/deepseek.py",
                         "research/deepseek_batch_window.py")}
        report["outputs"] = {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                             for name in ("scores.parquet", "scoring.toml", "design.toml", "prompt.txt",
                                          "requests.json", "battery.toml")}
        (output / "run.json").write_text(json.dumps(report, default=str, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
        return report
    finally:
        if cache:
            cache.close()
        if owned_client:
            client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--config", type=Path, default=Path("configs/research/deepseek_p7_v1.toml"))
    parser.add_argument("--design", type=Path, default=Path("configs/factors/p7_text_evaluation_v2.toml"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cache", type=Path, default=Path("artifacts/research/p7_deepseek_cache.sqlite"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--development-test", action="store_true",
                        help="Allow development requests during peak hours; budget caps still apply")
    parser.add_argument("--max-requests", type=int, default=0)
    parser.add_argument("--max-usd", type=float, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--publish-run", type=Path)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args()
    if args.publish_run:
        result = publish_panels(args.publish_run, data_root=args.data_root,
                                design=load_design(args.design))
    else:
        if not args.input or not args.output:
            parser.error("--input and a new --output directory are required")
        try:
            report = run_batch(source=args.input, config=args.config, design_path=args.design,
                               output=args.output, cache_path=args.cache, execute=args.execute,
                               max_requests=args.max_requests, max_usd=args.max_usd, limit=args.limit,
                               development_test=args.development_test)
        except (ValueError, RuntimeError) as exc:
            # Pydantic errors can echo supplied values: keep CLI failures path/key safe.
            parser.exit(2, f"Scoring stopped: {type(exc).__name__}; check config, local key and cache.\n")
        result = {"output": str(args.output), "plan": report["plan"], "summary": report["summary"],
                  "deferred_until": report['deferred_until'],
                  "requests_this_run": report["requests_this_run"]}
    print(json.dumps(result, ensure_ascii=False))
    if args.execute and not args.publish_run:
        excluded = {'missing_text', 'same_day_conflict', 'input_too_long', 'not_selected'}
        if any(count for state, count in report['summary'].items()
               if state not in excluded | {'success'}):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
