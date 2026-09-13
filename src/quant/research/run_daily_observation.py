"""Refresh and record independent research forecasts and frozen observation accounts."""
import argparse
import datetime as dt
import json
import os
import time
import tomllib
from pathlib import Path
from typing import Any, Callable

from quant.data.refresh import SHANGHAI, completed_date, latest_session
from quant.execution.cross_asset_forward import run as run_b20
from quant.execution.stock_paper import run as run_b32
from quant.execution.daily_observation_risk import DEFAULT_CONFIG, run as run_risk
from quant.reporting.rolling_signal_monitor import DEFAULT_CONFIG as MONITOR_CONFIG, run as run_monitor
from quant.reporting.stock_paper_monthly import ACCOUNTS, run as run_monthly
from quant.research.run_daily_model_forecast import run_daily


def _overlap(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def write_daily_report(record: dict[str, Any], output: Path) -> None:
    """Keep one readable summary beside the detailed stage artifacts."""
    names = {'calendar': '交易日历', 'model': '模型预测', 'refresh': '输入质量',
        'b20': 'B20六账户', 'b32': 'B32双账户', 'monthly': '月报',
        'risk': '订单风险', 'signal_monitor': '滚动信号监控'}
    statuses = {'complete': '完成', 'incomplete': '未完成', 'failed': '失败',
                'running': '进行中', 'skipped': '跳过'}
    lines = [f"# 日更记录：{record['as_of'] or record['requested_to']}", '',
        f"模式：{'历史演练' if record['rehearsal'] else '前向记录'}；"
        f"数据：{'已保存本地数据' if record['saved_data'] else '本次刷新'}；自动交易：关闭。", '',
        '|环节|结果|耗时（秒）|', '|---|---|---:|']
    for name, stage in record['stages'].items():
        seconds = stage.get('elapsed_seconds')
        duration = f'{seconds:.1f}' if seconds is not None else '—'
        lines.append(f"|{names.get(name, name)}|{statuses.get(stage['status'], stage['status'])}|{duration}|")
    model = record['stages'].get('model', {}).get('result', {})
    errors = model.get('input_errors', [])
    if model:
        lines += ['', f"本次模型预测：{model.get('prediction_stocks', 0)}只股票。"]
    if errors:
        lines += ['', '需处理的输入问题：', *['- '+str(error) for error in errors]]
    for name, stage in record['stages'].items():
        if stage.get('error'):
            lines += ['', f"{names.get(name, name)}：{stage['error']}"]
    risk = record['stages'].get('risk', {}).get('result', {})
    accounts = risk.get('accounts', [])
    if accounts:
        completed = sum(account.get('status') == 'complete' for account in accounts)
        lines += ['', f'账户风险检查：{completed}/{len(accounts)}份完成。']
        if risk.get('source_errors'):
            lines += ['风险汇总仍需处理上游问题：'+ '、'.join(
                names.get(name, '模型输入质量' if name == 'model_input_quality' else name)
                for name in risk['source_errors'])+'。']
    monitor = record['stages'].get('signal_monitor', {}).get('result', {})
    if monitor:
        lines += ['', f"滚动信号监控：{monitor.get('status')}；{monitor.get('reason', '详见评分记录')}。",
            '[预测评分与监控详情](signal_monitor/summary.json)']
        if monitor.get('status') == 'insufficient':
            lines += ['前向样本不足，尚未形成足够长度的监控窗口。']
    health = record.get('factor_health')
    if health:
        lines += ['', '## 因子健康日志', '']
        if health.get('status') == 'recorded':
            lines += [f"配置范围{health.get('factor_count')}项，其中{health.get('measured_factors')}项有有限值；"
                f"同日合格股票池{health.get('current_eligible_symbols')}只。"]
        elif health.get('status') == 'unavailable':
            lines += ['暂不可用：'+str(health.get('reason', '详见质量记录'))]
        else:
            lines += ['当前配置未启用健康日志。']
        if health.get('status') == 'recorded' and health.get('output'):
            target = Path(os.path.relpath(Path(health['output'])/'summary.json', output)).as_posix()
            lines += ['', f'[健康诊断详情]({target})；诊断数值不改变既有准入或持仓。']
    lines += ['', '[完整运行记录](summary.json)', '']
    temporary = output/'report.md.tmp'
    temporary.write_text('\n'.join(lines), encoding='utf-8')
    temporary.replace(output/'report.md')


def run(*, config: Path, output: Path, to: str = 'today', saved_data: bool = False,
        rehearsal: bool = False, account_root: Path | None = None,
        b20_output: Path | None = None, b32_output: Path | None = None,
        now: dt.datetime | None = None) -> dict[str, Any]:
    """Continue independent components; only monthly reporting depends on B32 success."""
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    if settings['auto_trade'] is not False:
        raise ValueError('Observation requires auto_trade=false')
    if settings.get('forecast_monitor') and Path(settings['forecast_monitor']['selection']).resolve() != Path(settings['model']['selection']).resolve():
        raise ValueError('Forecast monitor must use daily model frozen selection')
    defaults = [Path(settings[k]['output']).resolve() for k in ('b20', 'b32')]
    root = account_root.resolve() if account_root else None
    if rehearsal and root is None:
        raise ValueError('Rehearsal requires an isolated --account-root')
    accounts = [
        (override or (root / name if root else default)).resolve()
        for override, name, default in zip((b20_output, b32_output), ('b20', 'b32'), defaults)
    ]
    if _overlap(*accounts) or any(_overlap(output.resolve(), p) for p in accounts):
        raise ValueError('Record and account directories must be separate')
    if rehearsal and any(
        root not in p.parents or any(_overlap(p, default) for default in defaults)
        for p in accounts
    ):
        raise ValueError('Rehearsal accounts must stay below account-root, outside production')
    if output.exists():
        raise FileExistsError('Use a new daily summary directory')
    clock = now or dt.datetime.now(SHANGHAI)
    data_root, artifact_root = Path(settings['data_root']), Path(settings['artifact_root'])
    output.mkdir(parents=True)
    stages: dict[str, Any] = {}
    result: dict[str, Any] = {
        'requested_to': to, 'as_of': None, 'saved_data': saved_data, 'rehearsal': rehearsal,
        'auto_trade': False, 'conclusion': 'RESEARCH_ONLY', 'status': 'incomplete', 'stages': stages,
        'factor_health': None,
        'policy': 'B20 independent; B32 requires refresh success or saved-data; monthly requires B32.',
        'account_paths': dict(zip(('b20', 'b32'), map(str, accounts))),
    }

    def save_summary() -> None:
        temporary = output/'summary.json.tmp'
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str),
                             encoding='utf-8')
        temporary.replace(output/'summary.json')
        write_daily_report(result, output)

    save_summary()

    def stage(name: str, operation: Callable[[], dict], valid: Callable[[dict], bool]) -> bool:
        stages[name] = {'status': 'running'}
        save_summary()
        started = time.monotonic()
        try:
            value = operation()
            ok = valid(value)
            stages[name] = {'status': 'complete' if ok else 'incomplete', 'result': value}
        except Exception as exc:
            ok = False
            stages[name] = {'status': 'failed', 'error': f'{type(exc).__name__}: {exc}'}
        stages[name]['elapsed_seconds'] = round(time.monotonic() - started, 3)
        save_summary()
        return ok

    try:
        end = latest_session(data_root=data_root, through=completed_date(to, clock),
                             refresh_calendar=not saved_data)
    except Exception as exc:
        stages['calendar'] = {'status': 'failed', 'error': f'{type(exc).__name__}: {exc}'}
    else:
        date = str(end)
        result['as_of'] = date
        stage('model', lambda: run_daily(
            to=date, selection=Path(settings['model']['selection']), output=output/'model',
            data_root=data_root, refresh_config=Path(settings['refresh_config']),
            artifact_root=artifact_root, saved_data=saved_data,
            intraday=settings.get('intraday', True), rehearsal=rehearsal, now=clock),
            lambda value: value.get('as_of') == date and value.get('status') == 'recorded')
        try:
            refresh = json.loads((output/'model/refresh.json').read_text(encoding='utf-8'))
            result['factor_health'] = refresh['input_quality'].get('factor_health')
            refresh_errors = [*refresh['intraday_errors'], *refresh['input_quality']['errors']]
            if refresh['latest_session'] != date:
                refresh_errors.append('Refresh snapshot does not match requested session')
        except (OSError, ValueError, KeyError) as exc:
            refresh_errors = [f'Unavailable input-quality result: {type(exc).__name__}: {exc}']
        refresh_ok = not refresh_errors
        if settings.get('q10') and not rehearsal and end >= dt.date(2026, 9, 13):
            from quant.execution.q10_paper import run as run_q10
            stage('q10', lambda: run_q10(config_path=Path(settings['q10']['config']),
                data_root=data_root, output=Path(settings['q10']['output']), end=end,
                forecast=output/'model/forecast'),
                lambda value: value.get('as_of') == date)
        stages['refresh'] = {'status': 'complete' if refresh_ok else 'failed',
                             'mode': 'saved_data' if saved_data else 'refresh',
                             'input_errors': refresh_errors,
                             'path': str(output/'model/refresh.json')}
        stage('b20', lambda: run_b20(config_path=Path(settings['b20']['config']),
              data_root=data_root, output=accounts[0], end=end, refresh_data=not saved_data),
              lambda value: value.get('as_of') == date and len(value.get('accounts', [])) == 6
              and all(Path(a['output']).name == date for a in value['accounts']))
        stock_ok = False
        # Saved observation accounts retain their independent, snapshot-specific validation.
        if refresh_ok or saved_data:
            stock_ok = stage('b32', lambda: run_b32(
                config_path=Path(settings['b32']['config']), data_root=data_root,
                output=accounts[1], end=end), lambda value:
                {a['account'] for a in value.get('accounts', [])} == set(ACCOUNTS)
                and all(a['as_of'] == date for a in value['accounts']))
        else:
            stages['b32'] = {'status': 'skipped', 'reason': 'refresh did not complete'}
        if stock_ok:
            def monthly() -> dict:
                # The existing report reads latest snapshots, not an explicit requested date.
                for account in ACCOUNTS:
                    snapshots = sorted((accounts[1]/account).glob('????-??-??/state.json'))
                    if not snapshots or snapshots[-1].parent.name != date:
                        raise ValueError('Monthly source snapshots do not match requested session')
                folder = output/'monthly'
                value = run_monthly(ledger_root=accounts[1], data_root=data_root,
                                    artifact_root=artifact_root, output=folder)
                if value.get('action') == 'no-op':
                    value = json.loads((folder/'summary.json').read_text(encoding='utf-8'))
                return {**value, 'output': str(folder)}
            stage('monthly', monthly, lambda value: value.get('as_of') == date)
        else:
            stages['monthly'] = {'status': 'skipped', 'reason': 'B32 did not complete'}
    stage('risk', lambda: run_risk(record=result, output=output/'risk', data_root=data_root,
        config=Path(settings.get('risk_config', DEFAULT_CONFIG))),
        lambda value: value.get('status') == 'complete')
    if result['as_of'] is not None:
        def monitor() -> dict:
            if settings.get('forecast_monitor'):
                from quant.reporting.daily_forecast_monitor import run as continue_forecasts
                return continue_forecasts(config=config, known_through=end, output=output/'signal_monitor',
                    data_root=data_root, current=output/'model/forecast')
            return run_monitor(known_through=end, output=output/'signal_monitor',
                config=Path(settings.get('monitor_config', MONITOR_CONFIG)))
        stage('signal_monitor', monitor,
            lambda value: value.get('status') in ('insufficient', 'warning', 'observed', 'pending'))
    else:
        stages['signal_monitor'] = {'status': 'skipped', 'reason': 'No known session cutoff'}
    result['signal_monitor_status'] = stages['signal_monitor'].get('result', {}).get('status', 'unavailable')
    result['requires_review'] = (stages['risk'].get('result', {}).get('requires_review', True)
        or stages['signal_monitor'].get('result', {}).get('requires_review', True))
    result['status'] = ('complete' if stages and all(
        s['status'] == 'complete' for s in stages.values()) else 'incomplete')
    save_summary()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/research/daily_observation_q2_sue_v2_20260912.toml'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--to', default='today')
    parser.add_argument('--saved-data', action='store_true')
    parser.add_argument('--rehearsal', action='store_true')
    parser.add_argument('--account-root', type=Path)
    parser.add_argument('--b20-output', type=Path)
    parser.add_argument('--b32-output', type=Path)
    args = parser.parse_args()
    result = run(**vars(args))
    print(json.dumps(result, ensure_ascii=False, default=str))
    if result['status'] != 'complete':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
