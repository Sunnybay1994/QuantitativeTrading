"""Explain saved curve coverage without certifying unseen holdout performance."""
import datetime as dt
import tomllib
from pathlib import Path


def config_evidence(config: Path | None, root: Path) -> dict:
    result = {'training': '未知：源记录未提供训练区间',
              'evaluation': '未知：未找到冻结评估区间', 'sources': []}
    if config is None or not config.resolve().is_relative_to((root/'artifacts').resolve()):
        return result  # Mutable configurations cannot prove an old run's settings.
    if not config.is_file() or config.suffix != '.toml':
        return result
    try:
        data = tomllib.loads(config.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return result
    walk = data.get('walk_forward', {})
    result['sources'] = [str(config)]
    def date(key):
        try:
            return dt.date.fromisoformat(str(walk[key])).isoformat()
        except (KeyError, ValueError):
            return None
    start, end = date('test_start'), date('test_end')
    if start and end and start <= end:
        result['evaluation'] = f'冻结配置评估范围：{start} — {end}（实际覆盖以净值为准）'
    history = date('history_start')
    if history and walk.get('training') == 'expanding_history':
        result['training'] = f'配置为扩展窗口，历史起点 {history}；各折实际训练首末日未在此记录'
    return result


def describe_sample(spec: dict, dates: list[str]) -> dict:
    evidence = spec.get('sample_evidence') or {}
    paper = spec.get('kind') == 'paper'
    lines = [evidence.get('training', '未知：源记录未提供训练区间'),
             evidence.get('evaluation', '未知：未找到冻结评估区间'),
             ('模拟净值记录覆盖：' if paper else '保存回测净值覆盖：')+dates[0]+' — '+dates[-1],
             ('前向独立性未在本页面核验，需结合候选冻结记录；模拟净值不代表真实成交。' if paper else
              '独立测试／前向观察：此历史回放未提供独立性证明；逐年回放不等于从未看过的测试集。')]
    return {'lines': lines, 'sources': evidence.get('sources', [])}
