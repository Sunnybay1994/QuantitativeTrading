"""Interactive Feishu setup; no trading or outbound messages."""
import argparse
import getpass
import json
import os
import queue
import re
import secrets
import subprocess
import sys
import threading
import time
import warnings

import httpx

from quant.notify.feishu_credentials import load_local, save_local


def verify(app_id, secret):
    try:
        with httpx.Client(timeout=20, trust_env=False) as client:
            response = client.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                                   json={"app_id": app_id, "app_secret": secret})
            response.raise_for_status()
            row = response.json()
    except (httpx.HTTPError, ValueError):
        raise ValueError("无法访问飞书，请检查网络后重试。") from None
    if row.get("code") != 0 or not row.get("tenant_access_token"):
        raise ValueError("飞书未接受凭据，请核对 App ID / Secret。")


def match_binding(message, code):
    # Accept @bot prefixes, but require the complete random code as a token.
    if not re.search(r"(?<![A-Za-z0-9])"+re.escape(code)+r"(?![A-Za-z0-9])", message["text"]):
        return None
    return {k: message[k] for k in ("sender_id", "chat_id")}


def listener():
    row = json.loads(sys.stdin.readline())
    import lark_oapi as lark
    from lark_oapi.core.log import logger
    from quant.notify.feishu_manual import normalize_message_event
    logger.disabled = True

    def receive(event):
        try:
            message = normalize_message_event(json.loads(lark.JSON.marshal(event)))
            binding = match_binding(message, row["code"])
            if binding:
                print(json.dumps({"binding": binding}), flush=True)
        except (ValueError, KeyError):
            pass

    class Client(lark.ws.Client):
        async def _connect(self):
            await super()._connect()
            print(json.dumps({"connected": True}), flush=True)

    handler = lark.EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(receive).build()
    Client(row["app_id"], row["app_secret"], event_handler=handler, auto_reconnect=False).start()


def discover(app_id, secret, timeout=180):
    code = "".join(secrets.choice("23456789ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(5))
    process = subprocess.Popen([sys.executable, "-u", "-m", "quant.notify.feishu_setup", "--listen"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    events = queue.Queue()

    def reader():
        for line in process.stdout:
            try:
                events.put(json.loads(line))
            except ValueError:
                pass
        events.put({"closed": True})

    threading.Thread(target=reader, daemon=True).start()
    try:
        process.stdin.write(json.dumps(dict(app_id=app_id, app_secret=secret, code=code))+"\n")
        process.stdin.close()
        deadline, connected = time.monotonic()+90, False
        while time.monotonic() < deadline:
            try:
                event = events.get(timeout=min(1, max(.01, deadline-time.monotonic())))
            except queue.Empty:
                continue
            if event.get("connected") and not connected:
                connected, deadline = True, time.monotonic()+timeout
                print("连接成功。请现在给机器人发送以下口令（群聊请 @机器人）：\n"+code, flush=True)
            if connected and event.get("binding"):
                return event["binding"]
            if event.get("closed"):
                raise ValueError("连接已关闭，请核对飞书应用配置后重试。")
        raise ValueError("未收到绑定消息。请订阅 im.message.receive_v1、开启消息接收权限并发布应用，再重试。")
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)
        process.stdout.close()


def wizard():
    print("飞书接入向导：保存凭据 → 验证应用 → 发消息绑定。不会启动交易或发送消息。")
    if os.environ.get("FEISHU_APP_ID") or os.environ.get("FEISHU_APP_SECRET"):
        raise ValueError("请先清除当前终端 FEISHU_APP_ID / FEISHU_APP_SECRET 环境变量，避免覆盖本地配置。")
    try:
        current = load_local()
    except RuntimeError:
        print("旧凭据无法解密；可重新输入，确认完成前不会覆盖原文件。")
        current = None
    app_id = input("[1/3] App ID（已有配置可回车保留）：").strip() or (current or {}).get("app_id", "")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        secret = getpass.getpass("App Secret（隐藏输入；相同 App ID 可回车保留）：").strip()
    if not secret and current and app_id == current["app_id"]:
        secret = current["app_secret"]
    if not app_id or not secret:
        raise ValueError("App ID 和 Secret 不能为空。")
    print("[2/3] 正在验证应用身份……", flush=True)
    verify(app_id, secret)
    print("身份验证通过。请在飞书后台选择长连接、订阅 im.message.receive_v1，配置消息接收权限并发布应用。")
    input("准备好后按回车开始连接；等出现口令后再发送：")
    print("[3/3] 正在加载 SDK 并连接，首次可能需要一分钟……", flush=True)
    binding = discover(app_id, secret)
    print("已识别：\nsender_id="+binding["sender_id"]+"\nchat_id="+binding["chat_id"])
    if input("确认这是你刚发消息的会话？输入 y 保存，其他输入取消：").strip().lower() != "y":
        print("已取消，原配置未改变。")
        return
    save_local(app_id, secret, binding=binding)
    print("接入配置已加密保存到 configs/feishu.local.dpapi，重启仍可用。")
    print("交易服务仍关闭。接下来初始化演练账户；已有账户绑定不一致时须核对，不能自动迁移。")


def main():
    parser = argparse.ArgumentParser(description="飞书接入向导")
    parser.add_argument("--listen", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--status", action="store_true", help="查看本地配置状态，不联网")
    args = parser.parse_args()
    try:
        if args.listen:
            listener()
        elif args.status:
            row = load_local()
            print("凭据："+("已保存" if row else "未配置"))
            print("绑定："+("已保存" if row and row.get("binding") else "未配置"))
            print("本地状态不代表连接在线或交易服务已启动。")
        else:
            wizard()
    except (ValueError, RuntimeError, OSError, EOFError, KeyboardInterrupt, getpass.GetPassWarning) as exc:
        if args.listen:
            raise SystemExit(1) from None
        print("接入未完成："+(str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "已中断或终端不可用，请在交互终端重试。"))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
