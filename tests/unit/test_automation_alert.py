from types import SimpleNamespace
from quant.notify.automation_alert import report


def test_failure_throttle_recovery_and_new_exit(tmp_path):
    calls=[]
    def sender(title, body):
        calls.append((title,body))
        return [SimpleNamespace(channel='wxauto',ok=True,detail='submitted')]
    args=dict(root=tmp_path,sender=sender)
    assert report('task',1,'first.log',now=100,**args)['status']=='attempted'
    assert report('task',1,'second.log',now=200,**args)['status']=='suppressed'
    assert report('task',3,'third.log',now=300,**args)['status']=='attempted'
    assert report('task',0,'ok.log',now=400,**args)['status']=='healthy'
    assert report('task',3,'again.log',now=500,**args)['status']=='attempted'
    assert report('task',3,'hour.log',now=4100,**args)['status']=='attempted'
    assert len(calls)==4
    assert 'first.log' in calls[0][1]


def test_ambiguous_send_is_not_automatically_repeated(tmp_path):
    import pytest
    def uncertain(*args):
        raise TimeoutError('possibly submitted')
    with pytest.raises(TimeoutError):
        report('task',1,'log',root=tmp_path,now=100,sender=uncertain)
    assert report('task',1,'log',root=tmp_path,now=101,sender=uncertain)['status']=='suppressed'
