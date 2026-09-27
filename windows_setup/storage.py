"""Atomic setup records and Windows-protected secret blobs."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import secrets
import time

from beta_setup.core import SetupError, reject_links
from atomic_file import replace_file
from windows_setup.model import public_values


def atomic_json(path: Path, value: dict) -> None:
    reject_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(12))
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=True, sort_keys=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path, *, limit: int = 1024 * 1024) -> dict:
    reject_links(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise SetupError("導入記録を読み取れません。", "state_invalid")
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, UnicodeError):
        raise SetupError("導入記録の形式を確認できません。", "state_invalid") from None


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect(raw: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise SetupError("秘密情報の保護はWindowsで実行してください。", "windows_required")
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    memory = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    source = Blob(len(raw), memory)
    output = Blob()
    # Machine protection permits the installation's virtual service account to
    # decrypt. The containing directory must also have a restricted Windows ACL.
    flags = 0x01 if decrypt else 0x01 | 0x04  # UI_FORBIDDEN, LOCAL_MACHINE
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, flags, ctypes.byref(output)):
        raise SetupError("Windowsの秘密情報保護を実行できませんでした。", "secret_protection_failed")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.memset(output.data, 0, output.size)
        kernel.LocalFree(output.data)
        ctypes.memset(memory, 0, len(raw))


def save_secrets(path: Path, values: dict) -> None:
    reject_links(path)
    encrypted = protect(json.dumps(values, ensure_ascii=True).encode())
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(12))
    try:
        with temporary.open("xb") as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_secrets(path: Path) -> dict:
    reject_links(path)
    if not path.is_file() or path.stat().st_size > 256 * 1024:
        raise SetupError("保護された設定を読み取れません。", "secret_invalid")
    try:
        value = json.loads(protect(path.read_bytes(), decrypt=True))
        if not isinstance(value, dict):
            raise ValueError
        return value
    except ValueError:
        raise SetupError("保護された設定の形式が不正です。", "secret_invalid") from None


class DraftStore:
    def __init__(self, root: Path):
        self.path = root / ".server-setup" / "draft.json"

    def load(self) -> dict:
        if not self.path.exists():
            return {"flow": "home", "step": 0, "values": {}}
        record = read_json(self.path, limit=65536)
        if record.get("format") != 1:
            raise SetupError("下書きの形式が未対応です。", "draft_invalid")
        flow, step = record.get("flow"), record.get("step")
        self.validate_position(flow, step)
        return {"flow": flow, "step": step, "guide": self.guide_position(record.get("guide", {})),
                "values": self.sanitized_values(record.get("values", {}))}

    @staticmethod
    def validate_position(flow: str, step: int) -> None:
        if flow not in {"home", "lan", "public"} or type(step) is not int or not 0 <= step <= 5:
            raise SetupError("下書きの指定が不正です。", "draft_invalid")

    @staticmethod
    def guide_position(guide: dict) -> dict:
        if not isinstance(guide, dict):
            raise SetupError("下書きの手順が不正です。", "draft_invalid")
        result = {}
        for key, maximum in (("netStep", 7), ("tokenStep", 2), ("mailStep", 4)):
            value = guide.get(key, 0)
            if type(value) is not int or not 0 <= value <= maximum:
                raise SetupError("下書きの手順が不正です。", "draft_invalid")
            result[key] = value
        return result

    @staticmethod
    def sanitized_values(values: dict) -> dict:
        if not isinstance(values, dict):
            raise SetupError("下書きの形式が不正です。", "draft_invalid")
        from windows_setup.model import LAN_FIELDS
        allowed = LAN_FIELDS | {"publicHostname", "networkConfirmed", "domainReady", "trustPlan", "googleReady"}
        return {key: value for key, value in public_values(values).items()
                if key in allowed and (type(value) is bool or isinstance(value, str) and len(value) <= 2048)}

    def save(self, flow: str, step: int, values: dict, guide: dict | None = None) -> None:
        self.validate_position(flow, step)
        atomic_json(self.path, {"format": 1, "flow": flow, "step": step,
                                "guide": self.guide_position({} if guide is None else guide),
                                "values": self.sanitized_values(values), "saved_at": time.time()})
