"""Continue saved frozen-selection forecasts into monthly scoring and monitoring."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.reporting.rolling_signal_monitor import DEFAULT_CONFIG, run as run_monitor
from quant.research.score_model_forecasts import run_scores

_QUALIFICATION = ('source_selection', 'as_of', 'method', 'auto_trade', 'rehearsal', 'refit_close')


def _identical_late_copies(signal_day: str, rows: list) -> bool:
    """Same scores saved after the session are one sample. A same-day after-close record stays protected."""
    if any(identity.get('recorded_at') == f'{signal_day}:after_close' for _, identity, _ in rows):
        return False
    first = rows[0]
    return all(
        all(identity.get(key) == first[1].get(key) for key in _QUALIFICATION) and frame.equals(first[2])
        for _, identity, frame in rows)


def discover(*, settings: dict, known_through: dt.date, current: Path | None = None) -> dict:
    selection = Path(settings['selection']).resolve()
    decision = json.loads((selection/'selection.json').read_text(encoding='utf-8'))
    if not settings.get('roots') or not settings.get('patterns'):
        raise ValueError('Forecast search requires explicit roots and patterns')
    paths: set[Path] = set()
    errors: list[dict] = []
    ignored: list[str] = []
    future: list[str] = []
    duplicates: list[str] = []
    conflicts: list[dict] = []
    blocked_dates: set[str] = set()
    for value in settings['roots']:
        root = Path(value)
        if not root.is_dir():
            errors.append({'path': str(root), 'error': 'missing_search_root'})
            continue
        for pattern in settings['patterns']:
            if Path(pattern).is_absolute() or '..' in Path(pattern).parts:
                raise ValueError('Forecast patterns must stay within configured root')
            paths.update(p.resolve() for p in root.glob(pattern))
    if current is not None:
        if (current/'summary.json').is_file():
            paths.add((current/'summary.json').resolve())
        else:
            errors.append({'path': str(current), 'error': 'missing_current_forecast'})
    groups: dict[str, list] = {}
    for path in sorted(paths):
        signal_key = None
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            if Path(record['source_selection']).resolve() != selection:
                ignored.append(str(path.parent))
                continue
            day = dt.date.fromisoformat(record['as_of'])
            signal_key = str(day)
            if day > known_through:
                future.append(str(path.parent))
                continue
            if (record['method'] != decision['selected_method'] or record['auto_trade'] is not False
                    or type(record['rehearsal']) is not bool):
                raise ValueError('Forecast does not match frozen research method and qualification')
            predictions = pl.read_parquet(path.parent/'predictions.parquet').sort('trade_date', 'symbol')
            if predictions.is_empty():
                raise ValueError('Saved forecast has no predictions')
            # Qualification metadata is part of identity: a late/rehearsal rerun cannot replace a forward record.
            identity = {key: record.get(key) for key in (
                'source_selection', 'as_of', 'method', 'auto_trade', 'rehearsal', 'recorded_at', 'refit_close')}
            if record.get('recorded_at'):
                stamp = dt.datetime.fromisoformat(record['recorded_at'])
                if stamp.tzinfo is not None:
                    local = stamp.astimezone(dt.timezone(dt.timedelta(hours=8)))
                    if local.date() == day and local.hour >= 15:
                        identity['recorded_at'] = f'{day}:after_close'
            groups.setdefault(str(day), []).append((path.parent, identity, predictions))
        except (OSError, ValueError, KeyError, pl.exceptions.PolarsError) as exc:
            if signal_key is not None:
                blocked_dates.add(signal_key)
            errors.append({'path': str(path), 'error': f'{type(exc).__name__}: {exc}'})
    selected = []
    for signal_day, rows in sorted(groups.items()):
        first = rows[0]
        differs = any(identity != first[1] or not frame.equals(first[2]) for _, identity, frame in rows[1:])
        if signal_day in blocked_dates or (differs and not _identical_late_copies(signal_day, rows)):
            conflicts.append({'as_of': signal_day, 'paths': [str(row[0]) for row in rows]})
            continue
        selected.append(str(first[0]))
        duplicates.extend(str(row[0]) for row in rows[1:])
    return {'forecasts': selected, 'errors': errors, 'conflicts': conflicts,
        'duplicates': duplicates, 'ignored_other_selection': ignored, 'future_records': future}


def run(*, config: Path, known_through: dt.date, output: Path, data_root: Path = Path('data'),
        current: Path | None = None) -> dict:
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    if known_through > now.date() or (known_through == now.date() and now.hour < 15):
        raise ValueError('Require an actual completed scoring close')
    config_bytes = config.read_bytes()
    settings = tomllib.loads(config_bytes.decode('utf-8'))['forecast_monitor']
    if settings['auto_trade'] is not False:
        raise ValueError('Forecast monitoring cannot enable trading')
    output.mkdir(parents=True, exist_ok=False)
    (output/'daily_config.toml').write_bytes(config_bytes)
    result = {'known_through': str(known_through), 'source_selection': settings['selection'],
        'auto_trade': False, 'status': 'failed', 'requires_review': True,
        'forward_scored_series_months': 0, 'series': [], 'reason': '评分接续未完成'}
    try:
        found = discover(settings=settings, known_through=known_through, current=current)
        result['discovery'] = found
        if not found['forecasts']:
            result.update(status='conflict' if found['conflicts'] else ('failed' if found['errors'] else 'no_forecasts'),
                reason='预测存在冲突或缺输入' if found['conflicts'] or found['errors'] else '尚无该冻结版本的预测',
                requires_review=bool(found['errors'] or found['conflicts']))
        else:
            scored = run_scores(forecasts=[Path(p) for p in found['forecasts']],
                known_through=known_through, output=output/'scores', data_root=data_root)
            rows = pl.read_csv(output/'scores/monthly_scores.csv', try_parse_dates=True)
            statuses = dict(rows.group_by('status').len().iter_rows())
            result['scoring'] = {**scored, 'statuses': statuses}
            # Existing monitor casts all-null CSV IC to Float64 and accepts an empty typed label table.
            monitor_config = output/'monitor.toml'
            base = Path(settings.get('rolling_config', DEFAULT_CONFIG)).read_text(encoding='utf-8')
            if tomllib.loads(base).get('series'):
                raise ValueError('Automatic forecast monitor requires an unbound rolling config')
            monitor_config.write_text(base+'\n[[series]]\nid = "frozen_daily_model"\nkind = "model"\n'
                + 'scores = '+json.dumps(str((output/'scores/monthly_scores.csv').resolve()))+'\n'
                + 'labels = '+json.dumps(str((output/'scores/realized_labels.parquet').resolve()))+'\n'
                + 'context = "Frozen selection; only scheduled monthly forecasts are samples."\n', encoding='utf-8')
            monitored = run_monitor(known_through=known_through, output=output/'rolling', config=monitor_config)
            result.update(monitored)
            result['pending_records'] = statuses.get('awaiting_realized_return', 0)
            result['non_monthly_records'] = statuses.get('not_month_end_or_calendar_incomplete', 0)
            result['score_input_failures'] = sum(statuses.get(s, 0) for s in ('missing_predictions', 'insufficient_pairs'))
            if monitored['status'] == 'failed':
                result.update(status='failed', requires_review=True, reason='滚动监控输入或计算失败')
            elif result['score_input_failures'] or found['errors'] or found['conflicts']:
                result.update(status='partial', requires_review=True, reason='部分预测冲突、缺输入或评分覆盖不足')
            elif result['pending_records'] and result['forward_scored_series_months'] == 0:
                result.update(status='pending', reason='月末预测收益尚未到期；未积累足够前向')
    except Exception as exc:
        result.update(status='failed', requires_review=True, error=f'{type(exc).__name__}: {exc}')
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (output/'report.md').write_text('# 冻结预测评分接续\n\n'+result['reason']+'。\n\n'
        + f"状态：{result['status']}；前向有效月数：{result['forward_scored_series_months']}。\n\n"
        + '[发现、冲突与评分详情](summary.json)；只有已成熟的月末预测进入滚动统计，历史演练单列。\n', encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--known-through', type=dt.date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--current', type=Path, help='Explicit saved forecast directory, including isolated rehearsals')
    args = parser.parse_args()
    result = run(**vars(args))
    print(json.dumps({'status': result['status'], 'forward_months': result['forward_scored_series_months']}))
    if result['status'] in ('failed', 'partial', 'conflict'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
