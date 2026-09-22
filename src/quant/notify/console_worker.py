"""Bound Feishu text listener for the local notification console; no trading."""
import asyncio
import datetime as dt
import json
import os
import sys
import threading
import time

from quant.core.paths import project_paths
from quant.notify.feishu_credentials import load_local
from quant.execution.manual_session_service import instance_lock

ROOT = project_paths().artifacts / 'notify/console'
WRITE_LOCK = threading.Lock()


def write(name, value):
    ROOT.mkdir(parents=True, exist_ok=True)
    with WRITE_LOCK:
        target = ROOT / name
        tmp = target.with_suffix('.tmp')
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        tmp.replace(target)


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    run = sys.argv[1]
    state = dict(run=run, pid=os.getpid(), state='starting', connected=False, started=time.time())
    with instance_lock(ROOT/'listener.lock'):
        def publish():
            state['heartbeat'] = time.time()
            write('listener.json', state)
        publish()
        try:
            local = load_local()
            if not local or not local.get('binding'):
                raise ValueError('binding_required')
            binding = local['binding']
            import lark_oapi as lark
            from lark_oapi.core.log import logger
            from quant.notify.feishu_manual import normalize_message_event
            from quant.notify.console_receipts import Receipts
            from quant.notify.feishu_manual import FeishuManualTransport
            logger.disabled = True

            def receive(event):
                try:
                    msg = normalize_message_event(json.loads(lark.JSON.marshal(event)))
                except ValueError:
                    return
                if (msg['sender_id'], msg['chat_id']) != (binding['sender_id'], binding['chat_id']):
                    return
                receipts = Receipts(ROOT)
                try:
                    receipts.receive(msg)
                finally:
                    receipts.close()
                state['last_received'] = dt.datetime.now().isoformat()

            def send_acknowledgements():
                receipts = Receipts(ROOT)
                transport = FeishuManualTransport(local['app_id'],local['app_secret'],[binding['chat_id']])
                try:
                    receipts.dispatch(lambda text, identifier: transport.send_text(binding['chat_id'],text,identifier))
                finally:
                    transport.close()
                    receipts.close()

            async def acknowledgements():
                while not (ROOT/(run+'.stop')).exists():
                    await asyncio.to_thread(send_acknowledgements)
                    await asyncio.sleep(1)

            handler = lark.EventDispatcherHandler.builder('', '').register_p2_im_message_receive_v1(receive).build()
            client = lark.ws.Client(local['app_id'], local['app_secret'], event_handler=handler, auto_reconnect=False)
            async def run_listener():
                asyncio.create_task(acknowledgements())
                while not (ROOT/(run+'.stop')).exists():
                    try:
                        await asyncio.wait_for(client._connect(), 30)
                        state.update(state='listening', connected=True)
                        ping = asyncio.create_task(client._ping_loop())
                        try:
                            while client._conn is not None and not (ROOT/(run+'.stop')).exists():
                                publish()
                                await asyncio.sleep(1)
                        finally:
                            ping.cancel()
                            await asyncio.gather(ping, return_exceptions=True)
                            await client._disconnect()
                    except Exception as exc:
                        state.update(state='reconnecting', connected=False, error=type(exc).__name__)
                        publish()
                    if not (ROOT/(run+'.stop')).exists():
                        state.update(state='reconnecting', connected=False)
                        publish()
                        await asyncio.sleep(5)
                state.update(state='stopped', connected=False)
                publish()
            loop = asyncio.get_event_loop()
            loop.set_exception_handler(lambda *_: None)
            try:
                loop.run_until_complete(run_listener())
            finally:
                for task in asyncio.all_tasks(loop):
                    task.cancel()
                loop.run_until_complete(asyncio.gather(*asyncio.all_tasks(loop), return_exceptions=True))
                loop.close()
        except Exception as exc:
            state.update(state='failed', connected=False, error=type(exc).__name__)
            publish()


if __name__ == '__main__':
    main()
