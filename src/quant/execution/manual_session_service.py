"""Opt-in Feishu rehearsal listener. No strategy scheduler or broker API calls."""
from contextlib import contextmanager
import datetime as dt
import json
import os
from pathlib import Path
import threading
import tomllib

from quant.execution.manual_session import ManualSession, TZ


@contextmanager
def instance_lock(path):
    stream = path.open('a+b')
    try:
        stream.seek(0)
        if stream.read(1) == b'':
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        stream.close()  # OS lock releases after crashes too; do not unlink lockfile.


def load_settings(path):
    config = tomllib.loads(path.read_text(encoding='utf-8'))
    if (config.get('mode') != 'rehearsal' or config.get('auto_trade') is not False
            or config.get('live_notifications') is not False):
        raise ValueError('This release supports rehearsal only; live dispatch is not implemented')
    if type(config.get('enabled', False)) is not bool:
        raise ValueError('enabled must be a boolean')
    if config.get('broker') != '银河证券' or config.get('planned_capital') != 100000:
        raise ValueError('Require the agreed Galaxy 100k rehearsal profile')
    return config


def serve(database: Path, config_path: Path, *, send_rehearsal: bool):
    config = load_settings(config_path)
    if not send_rehearsal or not config.get('enabled'):
        raise ValueError('Feishu is disabled; enable config and explicitly use --send-rehearsal')
    sender, chat = config.get('sender_id', ''), config.get('chat_id', '')
    if not sender or not chat or not database.is_file():
        raise ValueError('Initialize the rehearsal and bind the intended sender/chat first')
    from quant.notify.feishu_credentials import credentials
    app_id, secret = credentials()
    from quant.notify.feishu_manual import FeishuManualTransport, run_long_connection
    import importlib
    importlib.import_module("lark_oapi")  # Fail before any outbound work if SDK is absent.
    stop = threading.Event()
    with instance_lock(database.with_suffix('.lock')):
        check = ManualSession(database)
        try:
            spec = check.meta('spec')
            if (spec['sender_id'], spec['chat_id']) != (sender, chat):
                raise ValueError('Configured sender/chat differs from persisted session')
        finally:
            check.close()

        def receive(envelope):
            # Drop unauthorized events without replying or changing the account.
            if (envelope['sender_id'], envelope['chat_id']) != (sender, chat):
                return
            session = ManualSession(database)
            try:
                session.receive(envelope)
            finally:
                session.close()

        def work():
            transport = FeishuManualTransport(app_id, secret, [chat])
            try:
                while not stop.is_set():
                    session = ManualSession(database)
                    try:
                        now = dt.datetime.now(TZ)
                        session.process(now=now)
                        session.dispatch(transport.send_text, now=now)
                        status = {'at': now.isoformat(), 'mode': 'rehearsal', 'auto_trade': False,
                                  'pending_reviews': sum(r['status'] == 'review' for r in session.snapshot()['inbox'])}
                        temporary = database.with_suffix('.heartbeat.tmp')
                        temporary.write_text(json.dumps(status), encoding='utf-8')
                        temporary.replace(database.with_suffix('.heartbeat.json'))
                    except Exception as exc:
                        print('Manual rehearsal worker error: '+type(exc).__name__, flush=True)
                    finally:
                        session.close()
                    stop.wait(1.)
            finally:
                transport.close()

        worker = threading.Thread(target=work, name='manual-rehearsal', daemon=True)
        worker.start()
        try:
            run_long_connection(app_id, secret, receive)
        finally:
            stop.set()
            worker.join(timeout=35)
