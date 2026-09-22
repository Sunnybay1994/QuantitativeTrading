"""Encrypted local outbound-channel settings shared by CLI and dashboard."""
import json
import os
from pathlib import Path
import tempfile
from quant.core.paths import project_paths
from quant.notify.feishu_credentials import protect

FIELDS = {"email": {"smtp_host", "smtp_port", "from_addr", "to_addrs", "username", "password"},
          "wecom": {"webhook"}, "feishu": {"webhook"}, "wxauto": {"group"}}


def load():
    path = project_paths().root / "configs/notify.local.dpapi"
    return json.loads(protect(path.read_bytes(), decrypt=True)) if path.exists() else {}


def save(channel, values, enabled):
    if channel not in FIELDS or not isinstance(values, dict) or set(values)-FIELDS[channel] or type(enabled) is not bool:
        raise ValueError("无效通道配置")
    current = load()
    previous = current.get(channel, {})
    row = {**previous, **{k: v for k, v in values.items() if v != ""}, "enabled": enabled}
    if channel == "email":
        row["smtp_port"] = int(row.get("smtp_port", 587))
        if not 1 <= row["smtp_port"] <= 65535:
            raise ValueError("SMTP端口无效")
        if isinstance(row.get("to_addrs"), str):
            row["to_addrs"] = [v.strip() for v in row["to_addrs"].split(',') if v.strip()]
    if channel in ("wecom", "feishu") and row.get("webhook"):
        from urllib.parse import urlparse
        domain = urlparse(row["webhook"])
        allowed = {"wecom": {"qyapi.weixin.qq.com"}, "feishu": {"open.feishu.cn", "open.larksuite.com"}}
        if domain.scheme != 'https' or domain.hostname not in allowed[channel] or domain.username:
            raise ValueError("请填写对应官方平台的HTTPS机器人地址")
    current[channel] = row
    path = project_paths().root / "configs/notify.local.dpapi"
    path.parent.mkdir(parents=True, exist_ok=True)
    encrypted = protect(json.dumps(current).encode())
    fd, name = tempfile.mkstemp(prefix='notify-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)


def overlay(config):
    stored = load()
    chosen = list(config.get('notify', {}).get('channels', []))
    for name, row in stored.items():
        if name not in FIELDS:
            continue
        if name in chosen:
            chosen.remove(name)
        if row.get('enabled'):
            chosen.append(name)
        config[name] = {**config.get(name, {}), **row}
    if stored:
        config['notify'] = {**config.get('notify', {}), 'channels': chosen}
    return config
