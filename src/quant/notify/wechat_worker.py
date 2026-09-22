"""Poll only the explicitly selected WeChat group; no history replay or trading."""
import hashlib
import json
import os
import sys
import time

from quant.execution.manual_session_service import instance_lock
from quant.notify.console_receipts import Receipts
from quant.reporting.notification_control import root
from quant.reporting.wechat import connect, desktop_lock


class NewMessages:
    def __init__(self):
        self.seen = set()
        self.ready = False

    def collect(self, messages, group):
        result = []
        for msg in messages:
            if not msg.message_id:
                raise RuntimeError('微信消息缺少标识，暂停监听以避免重复收信')
            key = hashlib.sha256((group+'\0'+msg.message_id).encode()).hexdigest()
            if self.ready and key not in self.seen and msg.source == 'friend' and msg.kind == 'text':
                result.append(dict(message_id='wxauto:'+key, text=msg.content,
                                   sent_at='', channel='wxauto', sender=msg.sender))
            self.seen.add(key)
        self.ready = True
        return result


def main():
    run = sys.argv[1]
    folder = root()
    state = dict(run=run, pid=os.getpid(), connected=False, state='starting')
    def publish(**values):
        state.update(values, heartbeat=time.time())
        tmp = folder/'wxauto-listener.tmp'
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        tmp.replace(folder/'wxauto-listener.json')
    with instance_lock(folder/'wxauto-listener.lock'):
        publish()
        tracker = NewMessages()
        client = None
        group = None
        while not (folder/(run+'.stop')).exists():
            try:
                from quant.notify import load_notify_config
                config = load_notify_config()
                target = str(config.get('wxauto', {}).get('group', '')).strip()
                if not target:
                    raise ValueError('请先保存微信精确群名')
                with desktop_lock():
                    if client is None or target != group:
                        client = connect(target)
                        client.select()
                        group = target
                        tracker = NewMessages()
                    # Do not continuously steal focus from another conversation.
                    messages = client.read()
                receipts = Receipts(folder)
                previous_seen, previous_ready = tracker.seen.copy(), tracker.ready
                try:
                    for msg in tracker.collect(messages, group):
                        if receipts.receive(msg):
                            state['last_received'] = time.strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    tracker.seen, tracker.ready = previous_seen, previous_ready
                    raise
                finally:
                    receipts.close()
                publish(state='listening', connected=True, error='', group=group)
            except Exception as exc:
                publish(state='waiting', connected=False, error=str(exc)[:240])
            for _ in range(20):
                if (folder/(run+'.stop')).exists():
                    break
                time.sleep(.1)
        publish(state='stopped', connected=False)


if __name__ == '__main__':
    main()
