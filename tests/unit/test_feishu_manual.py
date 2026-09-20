import json
import sys
from types import SimpleNamespace

import httpx
import pytest

from quant.notify.feishu_manual import (
    FeishuManualTransport,
    FeishuTransportError,
    normalize_message_event,
    run_long_connection,
)


def transport(handler):
    return FeishuManualTransport(
        "app", "secret-never-log", ["chat"], httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_acceptance_requires_business_success_and_id_and_reuses_uuid():
    requests = []

    def handler(request):
        requests.append(request)
        if "auth/v3" in request.url.path:
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token", "expire": 7200})
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "m1"}})

    client = transport(handler)
    for _ in range(2):
        assert client.send_text("chat", "成交确认", "stable-id") == {
            "message_id": "m1", "provider_accepted": True,
        }
    assert len(requests) == 3
    for request in requests[1:]:
        assert request.url.params["receive_id_type"] == "chat_id"
        assert request.headers["Authorization"] == "Bearer token"
        body = json.loads(request.content)
        assert body["uuid"] == "stable-id"
        assert json.loads(body["content"]) == {"text": "成交确认"}


@pytest.mark.parametrize("status,body", [
    (403, {"msg": "secret-never-log"}),
    (200, {"code": 99991663, "msg": "secret-never-log"}),
    (200, {"code": 0, "data": {}}),
    (200, {"code": False, "data": {"message_id": "m"}}),
    (200, []),
])
def test_message_errors_are_sanitized(status, body):
    def handler(request):
        if "auth/v3" in request.url.path:
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token", "expire": 7200})
        return httpx.Response(status, json=body)

    with pytest.raises(FeishuTransportError) as error:
        transport(handler).send_text("chat", "text", "id")
    assert "secret-never-log" not in str(error.value)


@pytest.mark.parametrize("body", [
    {"code": 1, "msg": "secret-never-log"}, {"code": 0},
    {"code": 0, "tenant_access_token": "token", "expire": -1},
])
def test_bad_token_never_sends(body):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json=body)

    with pytest.raises(FeishuTransportError):
        transport(handler).send_text("chat", "text", "id")
    assert len(paths) == 1 and "auth/v3" in paths[0]


def test_malformed_json_and_network_errors_sanitized():
    with pytest.raises(FeishuTransportError, match="invalid JSON"):
        transport(lambda _: httpx.Response(200, text="not-json-secret")).send_text("chat", "text", "id")

    def failure(request):
        raise httpx.ConnectError("secret-never-log", request=request)

    with pytest.raises(FeishuTransportError, match="network failure") as error:
        transport(failure).send_text("chat", "text", "id")
    assert "secret-never-log" not in str(error.value)


@pytest.mark.parametrize("chat,text,uuid", [("other", "text", "id"), ("chat", "", "id"),
                                            ("chat", "text", ""), ("chat", "text", "x" * 51)])
def test_invalid_send_never_calls_network(chat, text, uuid):
    def fail(_):
        pytest.fail("must not call HTTP")

    with pytest.raises(ValueError):
        transport(fail).send_text(chat, text, uuid)


def event():
    return {"header": {"event_type": "im.message.receive_v1"}, "event": {
        "sender": {"sender_type": "user", "sender_id": {"open_id": "ou_user"}},
        "message": {"message_type": "text", "message_id": "om_id", "chat_id": "oc_chat",
                    "create_time": "1608725989000", "content": '{"text":"成交 O1"}'},
    }}


def test_normalize_user_text_with_stable_identity_and_source_time():
    result = normalize_message_event(event())
    assert result["sender_id"] == "ou_user"
    assert result["message_id"] == "om_id"
    assert result["chat_id"] == "oc_chat"
    assert result["text"] == "成交 O1"
    assert result["source_timestamp"] == "1608725989000"
    assert result["sent_at"].startswith("2020-12-23")


@pytest.mark.parametrize("field,value", [
    ("message_type", "image"), ("message_id", ""), ("chat_id", None),
    ("content", "[]"), ("content", "bad-json"), ("content", '{"text":1}'),
    ("content", '{"text":" "}'), ("create_time", "nan"),
])
def test_reject_bad_message(field, value):
    payload = event()
    payload["event"]["message"][field] = value
    with pytest.raises(ValueError, match="malformed"):
        normalize_message_event(payload)


def test_reject_bot_or_unidentified_or_wrong_event():
    for modify in (
        lambda p: p["event"]["sender"].update(sender_type="app"),
        lambda p: p["event"]["sender"].update(sender_id={"user_id": "not-open-id"}),
        lambda p: p["header"].update(event_type="card.action.trigger"),
    ):
        payload = event()
        modify(payload)
        with pytest.raises(ValueError):
            normalize_message_event(payload)


def test_long_connection_enqueues_normalized_events_and_propagates_inbox_failure(monkeypatch):
    callbacks = []
    accepted = []

    class Builder:
        def register_p2_im_message_receive_v1(self, callback):
            callbacks.append(callback)
            return self

        def build(self):
            return self

    class Client:
        def __init__(self, app_id, app_secret, **kwargs):
            assert (app_id, app_secret) == ("app", "secret")
            assert "event_handler" in kwargs

        def start(self):
            callbacks[-1](event())

    sdk = SimpleNamespace(
        EventDispatcherHandler=SimpleNamespace(builder=lambda *_: Builder()),
        JSON=SimpleNamespace(marshal=json.dumps), ws=SimpleNamespace(Client=Client),
        LogLevel=SimpleNamespace(ERROR=40),
    )
    monkeypatch.setitem(sys.modules, "lark_oapi", sdk)
    run_long_connection("app", "secret", accepted.append)
    assert accepted[0]["sender_id"] == "ou_user"
    bad = event()
    bad["event"]["message"]["message_type"] = "image"
    callbacks[0](bad)
    assert len(accepted) == 1

    def disk_failure(_):
        raise OSError("inbox write failed")

    with pytest.raises(OSError, match="inbox write failed"):
        run_long_connection("app", "secret", disk_failure)
