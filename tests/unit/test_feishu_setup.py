import pytest
from quant.notify import feishu_setup as s


def test_code_matches_mentions_but_not_similar_token():
    msg = dict(sender_id="ou_test", chat_id="oc_test", text="@_user_1 A2B3C")
    assert s.match_binding(msg, "A2B3C") == dict(sender_id="ou_test", chat_id="oc_test")
    assert s.match_binding({**msg, "text": "A2B3CX"}, "A2B3C") is None


@pytest.mark.parametrize("confirm", ["y", "n"])
def test_wizard_commits_only_confirmed_pair(monkeypatch, confirm):
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    monkeypatch.setattr(s, "load_local", lambda: dict(app_id="id", app_secret="secret"))
    answers = iter(["", "", confirm])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(s.getpass, "getpass", lambda _: "")
    monkeypatch.setattr(s, "verify", lambda *args: None)
    monkeypatch.setattr(s, "discover", lambda *args: dict(sender_id="ou_t", chat_id="oc_t"))
    saved = []
    monkeypatch.setattr(s, "save_local", lambda *args, **kwargs: saved.append((args, kwargs)))
    s.wizard()
    assert bool(saved) == (confirm == "y")
    if saved:
        assert saved[0] == (("id", "secret"), {"binding": dict(sender_id="ou_t", chat_id="oc_t")})


def test_service_uses_binding_only_with_same_credentials(monkeypatch, tmp_path):
    from quant.execution.manual_session_service import load_settings
    from quant.notify import feishu_credentials as c
    path = tmp_path / "config.toml"
    path.write_text('broker="银河证券"\nplanned_capital=100000\nmode="rehearsal"\nauto_trade=false\nlive_notifications=false\nenabled=true\nsender_id=""\nchat_id=""', encoding="utf-8")
    monkeypatch.setattr(c, "load_local", lambda: dict(app_id="id", app_secret="secret", binding=dict(sender_id="ou_t", chat_id="oc_t")))
    monkeypatch.setattr(c, "credentials", lambda: ("id", "secret"))
    assert load_settings(path)["sender_id"] == "ou_t"
    monkeypatch.setattr(c, "credentials", lambda: ("other", "secret"))
    with pytest.raises(ValueError, match="different"):
        load_settings(path)
