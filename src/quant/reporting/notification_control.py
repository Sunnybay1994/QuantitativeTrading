"""Local dashboard notification configuration and a separately managed listener."""
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import uuid

from quant.core.paths import project_paths
from quant.notify import channel_settings
from quant.notify.feishu_credentials import load_local, save_local
from quant.notify.feishu_setup import discover, verify

LOCK = threading.RLock()
BINDING = {"state": "idle"}


def root():
    path = project_paths().artifacts / 'notify/console'
    path.mkdir(parents=True, exist_ok=True)
    return path


def read(name, fallback=None):
    path = root()/name
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else fallback


def alive(pid):
    if not pid:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = wintypes.DWORD()
        try:
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def status():
    from quant.notify import load_notify_config
    config = load_notify_config()
    settings = {name: {**config.get(name, {}), "enabled": bool(config.get("notify", {}).get("enabled", True) and name in config.get("notify", {}).get("channels", []))} for name in channel_settings.FIELDS}
    local = load_local()
    rows = []
    for name in channel_settings.FIELDS:
        row = settings.get(name, {})
        public = {k:v for k,v in row.items() if k not in ('password','webhook')}
        rows.append(dict(channel=name, values=public, enabled=row.get('enabled',False),
                         secret_saved=bool(row.get('password') or row.get('webhook')), listener_supported=False))
    service = read('listener.json', {})
    service['process_alive'] = alive(service.get('pid'))
    service['connected'] = bool(service.get('connected') and service['process_alive'] and time.time()-service.get('heartbeat',0)<15)
    from quant.notify.console_receipts import Receipts
    receipts = Receipts(root())
    try:
        received = receipts.recent()
    finally:
        receipts.close()
    return dict(channels=rows, app_configured=bool(local), binding=(local or {}).get('binding'),
                binding_progress=dict(BINDING), listener=service, received=received,
                last_send=read('send.json'), auto_trade=False)


def start():
    previous = read('listener.json', {})
    if alive(previous.get('pid')):
        return {'message':'监听进程已存在，请查看连接状态'}
    local = load_local()
    if not local or not local.get('binding'):
        raise ValueError('请先配置应用并完成绑定')
    run = uuid.uuid4().hex
    with (root()/'listener.log').open('ab') as log:
        child = subprocess.Popen([sys.executable,'-m','quant.notify.console_worker',run],
            cwd=project_paths().root, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    (root()/'listener.json').write_text(json.dumps(dict(run=run,pid=child.pid,state='starting',heartbeat=time.time())),encoding='utf-8')
    return {'message':'已启动监听进程，SDK加载后显示连接状态'}


def stop():
    state = read('listener.json', {})
    if state.get('run') and alive(state.get('pid')):
        (root()/(state['run']+'.stop')).touch()
        return {'message':'已请求停止监听，等待进程退出'}
    return {'message':'监听未运行'}


def action(command, body):
    with LOCK:
        if command == 'save':
            channel_settings.save(body['channel'],body.get('values',{}),body['enabled'])
            return {'message':'通道配置已加密保存；留空项保留原值'}
        if command == 'credentials':
            if alive(read('listener.json',{}).get('pid')) or BINDING.get('state') in ('connecting','waiting','found'):
                raise ValueError('请先停止监听并完成或取消绑定')
            old = load_local() or {}
            app_id = body.get('app_id') or old.get('app_id','')
            secret = body.get('app_secret') or (old.get('app_secret','') if app_id==old.get('app_id') else '')
            verify(app_id,secret)
            save_local(app_id,secret,binding=old.get('binding') if app_id==old.get('app_id') else None)
            return {'message':'凭据验证通过，已加密保存'}
        if command == 'start':
            return start()
        if command == 'stop':
            return stop()
        if command == 'bind':
            if alive(read('listener.json',{}).get('pid')):
                raise ValueError('请先停止消息监听，避免多个连接分流事件')
            if BINDING.get('state') in ('connecting','waiting'):
                return {'message':'绑定监听正在进行'}
            local = load_local()
            if not local:
                raise ValueError('请先保存应用凭据')
            code = ''.join(secrets.choice('23456789ABCDEFGHJKLMNPQRSTUVWXYZ') for _ in range(5))
            BINDING.clear()
            BINDING.update(state='connecting',code=code)
            def work():
                try:
                    found = discover(local['app_id'],local['app_secret'],code=code,
                                     on_connected=lambda: BINDING.update(state='waiting'))
                    BINDING.update(state='found',candidate=found)
                except Exception:
                    BINDING.update(state='failed',message='未收到绑定口令，请检查事件订阅/权限后重试')
            threading.Thread(target=work,daemon=True).start()
            return {'message':'正在连接；显示已连接后再发送口令'}
        if command == 'confirm-binding':
            if BINDING.get('state') != 'found':
                raise ValueError('尚未识别绑定消息')
            local = load_local()
            save_local(local['app_id'],local['app_secret'],binding=BINDING['candidate'])
            BINDING.clear()
            BINDING.update(state='idle')
            return {'message':'绑定已加密保存，交易服务未启用'}
        if command == 'test':
            channel = body['channel']
            if channel == 'feishu_app':
                local = load_local()
                if not local or not local.get('binding'):
                    raise ValueError('请先绑定')
                if not status()['listener'].get('connected'):
                    raise ValueError('请先启动监听并等待已连接，确保能读取测试回复')
                identifier = 'TEST'+time.strftime('%H%M%S')
                reply = f'成交 {identifier} v1 成交号=DEMO{identifier} 本次数量=100 成交价=10.00 时间={time.strftime("%H:%M:%S")} 费用=0'
                text = f'【交易通信演练・不要下真实单】\n虚构订单 {identifier}：600000.SH，模拟买入100股，示例价10.00元。仅验证消息收发，不构成交易建议，也不记入实盘。\n请复制以下虚构成交回复：\n{reply}'
                from quant.notify.feishu_manual import FeishuManualTransport
                transport = FeishuManualTransport(local['app_id'],local['app_secret'],[local['binding']['chat_id']])
                try:
                    result = transport.send_text(local['binding']['chat_id'],text,uuid.uuid4().hex)
                finally:
                    transport.close()
                result.update(channel=channel,order_id=identifier,expected_reply=reply)
            else:
                if channel not in channel_settings.FIELDS:
                    raise ValueError('未知通道')
                from quant.notify import send
                result = {'channel':channel,'results':[vars(r) for r in send('通知通道测试','仅测试消息送达，不包含交易指令。',channels=[channel])]}
            result['at'] = time.strftime('%Y-%m-%d %H:%M:%S')
            (root()/'send.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
            if channel != 'feishu_app':
                sent = next((r for r in result['results'] if r['channel'] == channel), None)
                if not sent or not sent['ok']:
                    detail = sent['detail'] if sent else '未调用发送渠道，请检查通知总开关'
                    return {'message':'测试未送达：'+detail+'。本地待发记录不代表已发送。', 'result':result}
            return {'message':'测试已提交，请核对实际收信', 'result':result}
        raise ValueError('未知操作')
