from types import SimpleNamespace

import pytest

from quant.reporting.wechat import WeChatNotifier


class FakeWeChat:
    def __init__(self):
        self.info = {"chat_name": "原神启动", "chat_type": "group"}
        self.sent = []
        self.result = {"status": "成功"}

    def ChatInfo(self):
        return self.info

    def SendMsg(self, text):
        self.sent.append(text)
        return self.result

    def GetAllMessage(self):
        return [SimpleNamespace(content="回执 T1", type="text", attr="friend")]


@pytest.mark.parametrize("info", [None, {}, {"chat_name": "别的群", "chat_type": "group"},
                                  {"chat_name": "原神启动", "chat_type": "friend"}])
def test_wrong_or_unknown_target_never_sends(info):
    backend = FakeWeChat()
    backend.info = info
    with pytest.raises(RuntimeError):
        WeChatNotifier(backend, "原神启动").send("测试")
    assert backend.sent == []


@pytest.mark.parametrize("result", [None, {}, {"status": "失败"}])
def test_send_failure_is_not_retried(result):
    backend = FakeWeChat()
    backend.result = result
    with pytest.raises(RuntimeError):
        WeChatNotifier(backend, "原神启动").send("测试")
    assert backend.sent == ["测试"]


def test_submitted_is_not_recipient_acknowledgement():
    backend = FakeWeChat()
    result = WeChatNotifier(backend, "原神启动").send("测试")
    assert result["submitted"] is True
    assert result["recipient_acknowledged"] is False


def test_receive_preserves_source():
    result = WeChatNotifier(FakeWeChat(), "原神启动").read()
    assert result[0].content == "回执 T1"
    assert result[0].source == "friend"


@pytest.mark.parametrize("text", ["", " \n", "a" * 2001])
def test_invalid_text_never_sends(text):
    backend = FakeWeChat()
    with pytest.raises(ValueError):
        WeChatNotifier(backend, "原神启动").send(text)
    assert not backend.sent
