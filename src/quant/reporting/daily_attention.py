"""Explain review flags without mistaking completed diagnostics for trade orders."""


def attention(daily: dict) -> list[dict]:
    items = []
    for name, stage in daily.get('stages', {}).items():
        result = stage.get('result', {})
        if stage.get('status') not in ('complete', 'skipped'):
            items.append({'stage': name, 'reason': stage.get('error') or stage.get('reason') or '阶段未完成',
                          'action': '检查该阶段报告并修复输入或运行错误；不是下单通知。'})
        elif result.get('requires_review'):
            shadow = result.get('shadow', {})
            if name == 'forward_tracking' and shadow.get('missing_horizons'):
                items.append({'stage': name,
                    'reason': f"影子滑点缺少 {shadow['missing_horizons']} 个价格观察窗口（已观察 {shadow.get('observed_horizons', 0)} 个）；校准未完成。",
                    'action': '你无需操作或下单。这是数据维护项：需核对并补齐可得分钟成交量/成交额后重算；不能把缺口当零滑点。'})
                if shadow.get('errors'):
                    items.append({'stage': name, 'reason': str(shadow['errors']), 'action': '检查影子滑点报告中的计算错误。'})
            elif name == 'risk':
                for account in result.get('accounts', []):
                    if account.get('requires_review'):
                        items.append({'stage': name, 'reason': f"账户 {account['account']}：待核对 {account.get('issue_count', 0)} 个风险项 / {account.get('execution_plan_rows', 0)} 条执行计划。",
                                      'action': '查看账户风险报告确认原因；自动交易保持关闭。'})
                if result.get('source_errors'):
                    items.append({'stage': name, 'reason': str(result['source_errors']), 'action': '修复账户风险输入。'})
            else:
                items.append({'stage': name, 'reason': result.get('reason') or '该阶段标记需要复核',
                              'action': '查看该阶段报告；此提示不是订单指令。'})
    if daily.get('requires_review') and not items:
        items.append({'stage': 'summary', 'reason': '汇总标记需要复核，但未提供具体原因。',
                      'action': '检查原始日更报告，不能按无异常处理。'})
    return items
