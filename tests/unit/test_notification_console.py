import json
from types import SimpleNamespace
import pytest

from quant.notify import channel_settings as settings
from quant.reporting import notification_control as control


def test_status_never_returns_password_or_webhook(monkeypatch, tmp_path):
    monkeypatch.setattr(settings,'load',lambda: {'email':{'password':'SECRET','smtp_host':'host','enabled':True},'feishu':{'webhook':'SECRETURL'}})
    monkeypatch.setattr(control,'load_local',lambda: {'app_id':'APP','app_secret':'SECRET','binding':{'sender_id':'ou_a','chat_id':'oc_a'}})
    monkeypatch.setattr(control,'root',lambda:tmp_path)
    result=control.status()
    assert 'SECRET' not in json.dumps(result)
    assert result['app_configured']
    assert result['listener']['connected'] is False


def test_disabled_channel_overlay_removes_only_selected_channel(monkeypatch):
    monkeypatch.setattr(settings,'load',lambda: {'wecom':{'enabled':False},'email':{'enabled':True,'password':'s'}})
    result=settings.overlay({'notify':{'channels':['wecom','feishu']}})
    assert result['notify']['channels']==['feishu','email']
    assert result['email']['password']=='s'


def test_channel_encryption_roundtrip_and_blank_preserves(monkeypatch,tmp_path):
    monkeypatch.setattr(settings,'project_paths',lambda:SimpleNamespace(root=tmp_path))
    # Cipher mocked here; genuine DPAPI has its separate Windows roundtrip test.
    monkeypatch.setattr(settings,'protect',lambda data,**kwargs: data)
    settings.save('feishu',{'webhook':'https://open.feishu.cn/open-apis/bot/v2/hook/test'},True)
    settings.save('feishu',{'webhook':''},False)
    assert settings.load()['feishu']['webhook'].endswith('/test')
    assert settings.load()['feishu']['enabled'] is False
    with pytest.raises(ValueError):
        settings.save('feishu',{'webhook':'http://127.0.0.1/private'},True)


def test_stop_only_creates_owned_run_signal(monkeypatch,tmp_path):
    monkeypatch.setattr(control,'root',lambda:tmp_path)
    monkeypatch.setattr(control,'alive',lambda _:True)
    (tmp_path/'listener.json').write_text(json.dumps({'pid':123,'run':'abc'}))
    control.stop()
    assert (tmp_path/'abc.stop').exists()


def test_feishu_test_requires_live_listener(monkeypatch,tmp_path):
    monkeypatch.setattr(control,'root',lambda:tmp_path)
    monkeypatch.setattr(control,'load_local',lambda:{'binding':{'chat_id':'oc'}})
    monkeypatch.setattr(control,'status',lambda:{'listener':{'connected':False}})
    with pytest.raises(ValueError,match='监听'):
        control.action('test',{'channel':'feishu_app'})


def test_webhook_business_rejection_is_not_success(monkeypatch):
    import quant.notify as notify
    monkeypatch.setattr(notify.httpx,'post',lambda *a,**k:SimpleNamespace(status_code=200,json=lambda:{'code':19024}))
    assert not notify._post_webhook('feishu','https://open.feishu.cn/test',{}).ok
    monkeypatch.setattr(notify.httpx,'post',lambda *a,**k:SimpleNamespace(status_code=200,json=lambda:{'code':0}))
    assert notify._post_webhook('feishu','https://open.feishu.cn/test',{}).ok


def test_console_http_requires_same_origin_and_token(monkeypatch):
    import threading
    import httpx
    from quant.reporting.research_dashboard import create_server
    monkeypatch.setattr(control,'action',lambda *args:{'message':'ok'})
    server=create_server(0)
    t=threading.Thread(target=server.serve_forever,daemon=True)
    t.start()
    try:
        with httpx.Client(trust_env=False) as c:
            base=f'http://127.0.0.1:{server.server_port}'
            assert c.post(base+'/api/notifications/start',json={}).status_code==403
            import re
            html=c.get(base+'/').text
            token=re.search(r'id="notifications" data-token="([^"]+)',html).group(1)
            assert c.post(base+'/api/notifications/start',json={},headers={'Origin':base,'X-Mining-Token':token}).status_code==200
            assert c.post(base+'/api/notifications/start',json={},headers={'Origin':'http://evil.invalid','X-Mining-Token':token}).status_code==403
    finally:
        server.shutdown()
        server.server_close()
        t.join(3)


def test_receipts_deduplicate_and_recover_without_repeating_uncertain_ack(tmp_path):
    from quant.notify.console_receipts import Receipts
    msg=dict(message_id='m1',text='成交 TEST1 v1 成交号=DEMO1 本次数量=100 成交价=10.20 时间=11:31:17 费用=2',sent_at='2026-09-22T03:32:00Z')
    r=Receipts(tmp_path)
    assert r.receive(msg)
    assert not r.receive(msg)
    sent=[]
    def fail(text,identifier):
        sent.append(text)
        raise TimeoutError
    r.dispatch(fail)
    assert r.recent()[0]['ack_status']=='uncertain'
    assert r.recent()[0]['parsed']['price']=='10.2'
    r.close()
    r=Receipts(tmp_path)
    r.dispatch(fail)
    assert len(sent)==1
    r.receive({**msg,'message_id':'m2','text':'收到了么'})
    r.dispatch(lambda text,identifier:{'provider_accepted':True,'message_id':'ack2'})
    assert r.recent()[-1]['ack_status']=='accepted'
    r.close()


def test_failed_channel_outbox_is_not_reported_as_delivery(monkeypatch, tmp_path):
    import quant.notify as notify
    monkeypatch.setattr(control, 'root', lambda: tmp_path)
    monkeypatch.setattr(notify, 'send', lambda *a, **k: [
        notify.SendResult('wxauto', False, 'missing runtime'),
        notify.SendResult('outbox', True, 'local file'),
    ])
    result = control.action('test', {'channel': 'wxauto'})
    assert '测试未送达' in result['message']
    assert 'missing runtime' in result['message']
