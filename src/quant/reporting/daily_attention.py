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
                gaps = shadow.get('data_gaps', {})
                unavailable = sum(row['affected_observations'] for row in gaps.get('by_class', [])
                                  if row['gap_class'] == 'source_amount_unavailable')
                action = ('你无需操作或下单。当前ETF分钟源缺少成交额，重复抓取同源数据不能补齐；'
                          '需要有实际成交额的替代数据，缺口继续保留，不填零滑点。'
                          if unavailable == shadow['missing_horizons'] else
                          '你无需操作或下单。这是数据维护项：需核对并补齐可得分钟成交量/成交额后重算；不能把缺口当零滑点。')
                items.append({'stage': name,
                    'reason': f"影子滑点缺少 {shadow['missing_horizons']} 个价格观察窗口（已观察 {shadow.get('observed_horizons', 0)} 个）；校准未完成。",
                    'action': action})
                for recovery in shadow.get('local_minute_recovery', []):
                    if recovery.get('status') == 'recovered':
                        continue
                    reason = recovery.get('reason', '未提供原因')
                    if 'Turnover units inconsistent' in reason:
                        reason = '本地分钟成交额／成交量的隐含价格超出该分钟高低价，数据校验未通过'
                    elif 'Cross-source close mismatch' in reason:
                        reason = '本地与参考源的分钟收盘价差异超过允许范围'
                    elif 'Insufficient distinct reference bars' in reason:
                        reason = '参考源分钟覆盖不足，无法完成跨源校验'
                    elif '240 distinct' in reason:
                        reason = '本地目标日分钟记录不完整'
                    items.append({'stage': name,
                        'reason': f"{recovery.get('symbol', '未知标的')} / {recovery.get('date', '未知日期')}：{reason}。",
                        'action': '数据维护项，无需下单；核对 minute_recovery.json 的来源与失败原因，取得可验证数据后重算，不能放宽校验消除缺口。'})
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
