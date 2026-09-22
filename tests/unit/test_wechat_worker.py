from types import SimpleNamespace
from quant.notify.wechat_worker import NewMessages
from quant.notify.console_receipts import Receipts


def message(identifier, text='hello', source='friend'):
    return SimpleNamespace(message_id=identifier,content=text,source=source,kind='text',sender='tester')


def test_wechat_baseline_self_filter_and_duplicate_text():
    tracker=NewMessages()
    assert tracker.collect([message('old')], 'group')==[]
    rows=tracker.collect([message('old'),message('1'),message('2'),message('self',source='self')], 'group')
    assert len(rows)==2
    assert rows[0]['message_id']!=rows[1]['message_id']
    assert tracker.collect([message('1'),message('2')], 'group')==[]


def test_latest_order_reply_across_channels_and_no_cross_channel_ack(tmp_path):
    r=Receipts(tmp_path)
    base=dict(text='成交 TEST1 v1 成交号=DEMO1 本次数量=100 成交价=10.20 时间=11:31:17 费用=2',sent_at='')
    r.receive(dict(base,message_id='f1'))
    r.receive(dict(base,message_id='wxauto:w1',channel='wxauto'))
    assert r.latest_replies()['TEST1']['message_id']=='wxauto:w1'
    assert not r.receive(dict(base,message_id='f1'))
    assert r.latest_replies()['TEST1']['message_id']=='wxauto:w1'
    sent=[]
    r.dispatch(lambda text, identifier: sent.append(text) or dict(provider_accepted=True,message_id='ack'))
    assert len(sent)==1
    assert r.recent()[-1]['ack_status']=='received'
    r.receive(dict(base,message_id='f2'))
    assert r.latest_replies()['TEST1']['message_id']=='f2'
    r.close()


def test_broadcast_failure_does_not_skip_second_channel(monkeypatch):
    import quant.notify as notify
    monkeypatch.setattr(notify,'load_notify_config',lambda _: {'notify':{'enabled':True,'channels':['wxauto','feishu_app']}})
    sent=[]
    def first(*args):
        raise RuntimeError('offline')
    def second(*args):
        sent.append(args[:2])
        return notify.SendResult('feishu_app',True,'accepted')
    monkeypatch.setitem(notify._SENDERS,'wxauto',first)
    monkeypatch.setitem(notify._SENDERS,'feishu_app',second)
    results=notify.send('title','body')
    assert [r.ok for r in results]==[False,True]
    assert sent==[('title','body')]
