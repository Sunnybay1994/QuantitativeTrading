"""Feishu manual-execution rehearsal: durable replies, no broker connection."""
import argparse
import datetime as dt
import json
from pathlib import Path

from quant.execution.manual_session import ManualSession, TZ, dump


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def export(session, folder):
    folder.mkdir(parents=True, exist_ok=False)
    snapshot = session.snapshot()
    for name, value in [('summary', snapshot), ('opening', session.meta('opening')),
                        ('events', session.events()), ('sessions', session.meta('sessions'))]:
        (folder/(name+'.json')).write_text(dump(value)+'\n', encoding='utf-8')
    lines = ['# 银河10万元人工交易演练', '', '不是实盘成交记录；auto_trade=false。',
             '现金/持仓来自人工回报，未核对券商；待核费用不能当成0费用最终收益。', '',
             '|建议|证券|方向|计划量|实成量|状态|', '|---|---|---|---:|---:|---|']
    for row in snapshot['orders']:
        lines.append(f"|{row['order_id']}|{row['symbol']}|{row['side']}|{row['quantity']}|"
                     f"{row['filled_quantity']}|{row['state']}|")
    (folder/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return snapshot


def demo(folder):
    """Run fake orders/replies against real durable storage, without a network."""
    folder.mkdir(parents=True, exist_ok=False)
    session = ManualSession(folder/'session.sqlite')
    try:
        session.initialize(opening={'date': '2026-09-18', 'cash': 100000., 'holdings': {}},
                           sessions=['2026-09-21', '2026-09-22', '2026-09-23'],
                           account_id='galaxy_demo', sender_id='demo_user', chat_id='demo_chat')
        now = dt.datetime(2026, 9, 21, 9, 31, tzinfo=TZ)
        for identifier, symbol in [('O001', '600000.SH'), ('O002', '000001.SZ')]:
            session.add_order(dict(order_id=identifier, version=1, account_id='galaxy_demo',
                strategy_version='DEMO_ONLY', symbol=symbol, side='BUY', quantity=1000,
                limit_price='10.52', signal_at='2026-09-18T21:30:00+08:00',
                valid_from='2026-09-21T09:30:00+08:00', valid_until='2026-09-21T09:35:00+08:00'), now=now)
        session.dispatch(lambda *args: {'message_id': 'fake_'+args[-1], 'provider_accepted': True}, now=now)
        replies = [
            '委托 O001 v1 券商单号=B123 数量=1000 限价=10.52 时间=09:31:05',
            '成交 O001 v1 成交号=F456 本次数量=400 成交价=10.50 时间=09:31:18 费用=待核',
            '成交 O001 v1 成交号=F457 本次数量=600 成交价=10.51 时间=09:31:36 费用=待核',
            '未操作 O002 v1 确认未委托=是 原因=错过窗口',
            '费用确认 O001 v1 成交号=F456 费用=0.00',
            '费用确认 O001 v1 成交号=F457 费用=5.00',
        ]
        for index, text in enumerate(replies):
            session.receive(dict(message_id=str(index), sender_id='demo_user', chat_id='demo_chat', text=text))
        session.process(now=now.replace(hour=10))
        session.receive(dict(message_id='duplicate_fill', sender_id='demo_user', chat_id='demo_chat', text=replies[1]))
        session.process(now=now.replace(hour=10))
        result = export(session, folder/'report')
        assert result['book']['holdings']['600000.SH']['quantity'] == 1000
        assert abs(result['book']['cash']-89489.) < 1e-8
        assert result['fee_pending_fills'] == 0
        assert not any(r['status'] == 'review' for r in result['inbox'])
        return {'output': str(folder), 'cash': result['book']['cash'], 'shares': 1000,
                'network_used': False, 'auto_trade': False, 'mode': 'rehearsal'}
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path('artifacts/manual/galaxy_100k_rehearsal/session.sqlite'))
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    init.add_argument('--opening', type=Path, required=True)
    init.add_argument('--sessions', type=Path, required=True)
    init.add_argument('--account', required=True)
    init.add_argument('--sender', required=True)
    init.add_argument('--chat', required=True)
    orders = sub.add_parser('propose')
    orders.add_argument('--file', type=Path, required=True)
    inbox = sub.add_parser('receive')
    inbox.add_argument('--file', type=Path, required=True)
    sub.add_parser('process')
    sub.add_parser('status')
    show = sub.add_parser('export')
    show.add_argument('--output', type=Path, required=True)
    review = sub.add_parser('resolve')
    review.add_argument('--message-id', required=True)
    review.add_argument('--retry', action='store_true')
    review.add_argument('--reason', required=True)
    test = sub.add_parser('demo')
    test.add_argument('--output', type=Path, required=True)
    serve = sub.add_parser('serve')
    serve.add_argument('--config', type=Path, default=Path('configs/trading/manual_galaxy_100k.toml'))
    serve.add_argument('--send-rehearsal', action='store_true')
    args = parser.parse_args()
    if args.command == 'demo':
        print(dump(demo(args.output)))
        return
    if args.command == 'serve':
        from quant.execution.manual_session_service import serve as run
        run(args.database, args.config, send_rehearsal=args.send_rehearsal)
        return
    session = ManualSession(args.database)
    try:
        now = dt.datetime.now(TZ)
        if args.command == 'init':
            session.initialize(opening=read(args.opening), sessions=read(args.sessions),
                               account_id=args.account, sender_id=args.sender, chat_id=args.chat)
            result = {'initialized': True, 'mode': 'rehearsal'}
        elif args.command == 'propose':
            result = [session.add_order(row, now=now) for row in read(args.file)]
        elif args.command == 'receive':
            result = session.receive(read(args.file))
        elif args.command == 'process':
            result = session.process(now=now)
            session.tick(now=now)
        elif args.command == 'resolve':
            session.resolve_review(args.message_id, retry=args.retry, reason=args.reason)
            result = {'resolution_recorded': True}
        elif args.command == 'export':
            result = export(session, args.output)
        else:
            result = session.snapshot()
        print(dump(result))
    finally:
        session.close()


if __name__ == '__main__':
    main()
