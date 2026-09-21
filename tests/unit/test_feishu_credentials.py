import os
import subprocess
import sys

import pytest

from quant.notify import feishu_credentials as c


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_encrypted_roundtrip_update_and_fresh_process(tmp_path):
    path = tmp_path / "secret.bin"
    c.save_local("cli_test", "fake_secret_123", path)
    assert b"fake_secret_123" not in path.read_bytes()
    assert c.load_local(path)["app_secret"] == "fake_secret_123"
    c.save_local("cli_new", "fake_new_456", path)
    code = "from pathlib import Path; from quant.notify.feishu_credentials import load_local; import sys; assert load_local(Path(sys.argv[1]))['app_secret']=='fake_new_456'"
    subprocess.run([sys.executable, "-c", code, str(path)], check=True)
    path.write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="Cannot read"):
        c.load_local(path)


def test_environment_precedence_and_partial_pair_rejected(monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "env_id")
    monkeypatch.setenv("FEISHU_APP_SECRET", "env_secret")
    monkeypatch.setattr(c, "load_local", lambda: pytest.fail("Must not read file"))
    assert c.credentials() == ("env_id", "env_secret")
    monkeypatch.delenv("FEISHU_APP_SECRET")
    with pytest.raises(ValueError, match="both"):
        c.credentials()


def test_service_credentials_use_local_pair(monkeypatch):
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    monkeypatch.setattr(c, "load_local", lambda: dict(app_id="id", app_secret="secret"))
    assert c.credentials() == ("id", "secret")


def test_empty_update_preserves_file(tmp_path):
    path = tmp_path / "secret.bin"
    path.write_bytes(b"old")
    with pytest.raises(ValueError):
        c.save_local("id", "", path)
    assert path.read_bytes() == b"old"
