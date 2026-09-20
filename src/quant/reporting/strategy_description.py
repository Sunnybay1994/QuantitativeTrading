"""Short factual descriptions, sourced from frozen experiment configuration."""
from pathlib import Path
import tomllib


def describe(config: Path | None, variant: str) -> str:
    if config is None or not config.is_file():
        return f'{variant}：历史保存的账户净值；源记录未提供策略说明。'
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    research = settings.get('research', settings)
    if (variant.startswith('capital_') and settings.get('initial_capitals')
            and settings.get('interpretation') == 'capacity_constrained_fixed_slippage_sensitivity_not_calibrated_market_impact'):
        return (f"沿用冻结源策略信号，按 {int(variant[8:]) / 10000:g} 万元初始资金回放；"
                f"单笔成交参与率上限 {settings['participation_limit']:.0%}，"
                f"月度单边换手预算 {settings['monthly_turnover_budget']:.0%}。"
                '缺失成交容量时保留原持仓，未成交订单沿用月度调仓安排；'
                '这是固定滑点下的容量敏感性回放，尚未校准市场冲击。')
    if (settings.get('policy', {}).get('monthly_one_way_budget') == .5
            and settings.get('policy', {}).get('baseline') == 'corrected_sue_v2_causal48_model_without_concentration_caps'):
        base = f"沿用 SUE v2 LightGBM 评分，主组合选取 {research.get('top_k', 50)} 只股票，按月调仓。"
        return base + ('对照组不施加本实验的换手预算。' if variant == 'control' else
                       '以信号日实际持仓为起点，每月单边目标调整预算为净值的 50%，未用预算不结转；实际成交仍受原交易限制。')
    explicit = research.get('description') or research.get('hypothesis')
    if explicit:
        if explicit == 'Fixed industry and size constraints reduce Q10 drawdown without losing more than 2 percentage points of active CAGR.':
            return ('以 Q10 为基础，在原组合上施加固定行业和市值暴露约束；目标是降低回撤，'
                    '收益与回撤效果以实际报告为准。' if variant != 'control' else 'Q10 原组合对照，不施加本实验新增的行业和市值暴露约束。')
        prefix = '策略说明' if research.get('description') else '原配置假设（不代表已验证）'
        return f'{variant} · {prefix}：{explicit}'
    portfolio = settings.get('portfolio', {})
    details = [f'{variant}：按已冻结的模型信号构建组合']
    if portfolio.get('primary_top_k'):
        details.append(f"主组合持有评分靠前的 {portfolio['primary_top_k']} 只股票")
    details.append('成交限制和成本沿用原回测；原配置未提供经济机制说明')
    return '；'.join(details)+'。'
