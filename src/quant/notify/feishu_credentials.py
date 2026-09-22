"""Current-user Windows DPAPI storage for Feishu application credentials."""
import argparse
import ctypes
from ctypes import wintypes
import getpass
import json
import os
from pathlib import Path
import tempfile


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect(data: bytes, *, decrypt=False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Local credential storage requires Windows")
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise RuntimeError("Windows credential encryption/decryption failed")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))


def credential_path():
    from quant.core.paths import project_paths
    return project_paths().root / "configs" / "feishu.local.dpapi"


def load_local(path=None):
    path = path or credential_path()
    if not path.exists():
        return None
    try:
        row = json.loads(protect(path.read_bytes(), decrypt=True))
        if not all(isinstance(row.get(k), str) and row[k].strip() for k in ("app_id", "app_secret")):
            raise ValueError
        return row
    except (ValueError, OSError, RuntimeError):
        raise RuntimeError("Cannot read local Feishu credentials; run setup again as the same Windows user") from None


def save_local(app_id, app_secret, path=None, *, binding=None):
    if not app_id.strip() or not app_secret.strip():
        raise ValueError("App ID and Secret must not be empty")
    row = dict(app_id=app_id.strip(), app_secret=app_secret.strip())
    if binding:
        row["binding"] = binding
    encrypted = protect(json.dumps(row).encode())
    path = path or credential_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="feishu-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def credentials():
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    if app_id or secret:
        if not app_id or not secret:
            raise ValueError("Set both FEISHU_APP_ID and FEISHU_APP_SECRET, or remove both to use local credentials")
        return app_id, secret
    row = load_local()
    if row is None:
        raise ValueError("Configure FEISHU_APP_ID and FEISHU_APP_SECRET or run scripts/configure_feishu.ps1")
    return row["app_id"], row["app_secret"]


def main():
    parser = argparse.ArgumentParser(description="Save/update Feishu credentials using Windows user encryption")
    parser.add_argument("--status", action="store_true", help="Check storage without displaying credentials")
    args = parser.parse_args()
    if args.status:
        print("Local credentials available" if load_local() else "Local credentials not configured")
        return
    # No secret command-line arguments: avoid shell history and process listings.
    try:
        current = load_local()
    except RuntimeError:
        print("Existing credentials cannot be decrypted; enter both values to replace them.")
        current = None
    app_id = input("App ID (Enter keeps existing): " if current else "App ID: ").strip()
    if current and not app_id:
        app_id = current["app_id"]
    secret = getpass.getpass("App Secret (hidden; Enter keeps existing for same App ID): ").strip()
    if current and not secret and app_id == current["app_id"]:
        secret = current["app_secret"]
    save_local(app_id, secret)
    print("Saved with Windows user encryption. Restart the Feishu service to apply.")
    if os.environ.get("FEISHU_APP_ID") or os.environ.get("FEISHU_APP_SECRET"):
        print("Environment credentials override this file; remove both variables to use local storage.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as exc:
        raise SystemExit(str(exc)) from None
