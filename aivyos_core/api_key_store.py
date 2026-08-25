"""API Key 持久化存储 — 加密保存到本地文件，重启后自动恢复。

安全设计：
- 使用 Fernet (对称加密) 加密存储在磁盘上的 API Key
- 加密密钥派生自机器特征 (MAC 地址 + 主机名)，防止文件被拷贝到其他机器解密
- 仅返回元信息 (has_key, key_length, 脱敏预览)，永不回传明文
- 文件权限设置为仅当前用户可读写
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import socket
import stat
import struct
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# 尝试导入加密库
try:
    from cryptography.fernet import Fernet, InvalidToken
    _HAS_CRYPTOGRAPHY = True
except ImportError:
    _HAS_CRYPTOGRAPHY = False
    # 回退：使用简单的 XOR + base64 混淆（不追求强安全，仅防明文泄露）


def _get_machine_fingerprint() -> str:
    """获取机器指纹用于派生加密密钥。

    Returns:
        基于主机名和 MAC 地址的唯一指纹字符串。
    """
    parts = [socket.gethostname()]
    try:
        # 获取第一个非回环网络接口的 MAC 地址
        import uuid
        mac = uuid.getnode()
        parts.append(f"{mac:012x}")
    except Exception as e:
        log.debug("忽略预期内异常: %s", e, exc_info=True)
    return "-".join(parts)


def _derive_fernet_key(fingerprint: str) -> bytes:
    """从机器指纹派生 Fernet 密钥。

    Args:
        fingerprint: 机器指纹字符串。

    Returns:
        32 字节的 URL-safe base64 编码密钥。
    """
    digest = hashlib.sha256(f"aivyos-apikey-store:{fingerprint}".encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _derive_key_material(fingerprint: str, salt: bytes) -> bytes:
    """用 PBKDF2-HMAC-SHA256 从指纹+盐派生 64 字节密钥材料。

    前 32 字节用于 XOR 加密，后 32 字节用于 HMAC 完整性校验。
    仅使用 stdlib（hashlib），无需额外依赖。
    """
    return hashlib.pbkdf2_hmac(
        "sha256",
        fingerprint.encode("utf-8"),
        salt,
        iterations=100_000,
        dklen=64,
    )


def _simple_encrypt(plaintext: str, key: str) -> str:
    """强化版加密：salt + PBKDF2 + XOR + HMAC + base64。

    格式：base64(salt[16] || ciphertext || hmac[32])

    Args:
        plaintext: 明文字符串。
        key: 机器指纹（用于派生密钥）。

    Returns:
        Base64 编码的密文。
    """
    import hmac as _hmac
    import secrets

    salt = secrets.token_bytes(16)
    material = _derive_key_material(key, salt)
    enc_key, mac_key = material[:32], material[32:]

    plain_bytes = plaintext.encode("utf-8")
    ciphertext = bytes([b ^ enc_key[i % len(enc_key)] for i, b in enumerate(plain_bytes)])

    mac = _hmac.new(mac_key, salt + ciphertext, hashlib.sha256).digest()
    return base64.b64encode(salt + ciphertext + mac).decode("ascii")


def _simple_decrypt(ciphertext: str, key: str) -> str:
    """解密强化版格式，验证 HMAC 防篡改。

    Args:
        ciphertext: Base64 编码的密文。
        key: 机器指纹。

    Returns:
        解密后的明文字符串。HMAC 验证失败或格式错误返回空串。
    """
    import hmac as _hmac

    padded = ciphertext + "=" * (-len(ciphertext) % 4)
    try:
        raw = base64.b64decode(padded)
    except Exception:
        return ""

    # 最小长度：16(salt) + 0(明文) + 32(hmac) = 48
    if len(raw) < 48:
        # 可能是旧版 XOR 格式（无 salt+hmac），尝试旧方案解密
        return _legacy_decrypt(ciphertext, key)

    salt = raw[:16]
    mac = raw[-32:]
    ct = raw[16:-32]

    material = _derive_key_material(key, salt)
    enc_key, mac_key = material[:32], material[32:]

    expected_mac = _hmac.new(mac_key, salt + ct, hashlib.sha256).digest()
    if not _hmac.compare_digest(mac, expected_mac):
        log.error(
            "API Key HMAC 验证失败：数据可能被篡改、跨机器复制或存储文件损坏；"
            "相关 Key 已被跳过，请检查 api_keys.enc 是否被异常修改"
        )
        return ""

    decrypted = bytes([b ^ enc_key[i % len(enc_key)] for i, b in enumerate(ct)])
    try:
        return decrypted.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return ""


def _legacy_decrypt(ciphertext: str, key: str) -> str:
    """旧版纯 XOR + base64 解密（向后兼容已有存储文件）。"""
    key_bytes = key.encode("utf-8")
    padded = ciphertext + "=" * (-len(ciphertext) % 4)
    try:
        cipher_bytes = base64.b64decode(padded)
    except Exception:
        return ""
    decrypted = bytes([b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(cipher_bytes)])
    try:
        return decrypted.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return ""


class ApiKeyStore:
    """API Key 持久化存储管理器。

    功能：
    - 加密存储 API Key 到本地 JSON 文件
    - 启动时自动加载到 os.environ
    - 支持增/删/查/改操作
    - 返回脱敏预览，不暴露明文

    存储格式 (api_keys.enc):
    {
        "version": 1,
        "keys": {
            "DEEPSEEK_API_KEY": {
                "encrypted_value": "...",
                "provider": "deepseek",
                "updated_at": 1234567890.0
            }
        }
    }
    """

    def __init__(self, storage_path: Optional[str | Path] = None):
        """初始化存储管理器。

        Args:
            storage_path: 存储文件路径，默认 ~/.aivyos/api_keys.enc
        """
        if storage_path:
            self._path = Path(storage_path)
        else:
            home = Path(os.environ.get("AIVYOS_HOME", Path.home() / ".aivyos"))
            self._path = home / "api_keys.enc"

        self._fingerprint = _get_machine_fingerprint()
        self._fernet_key = _derive_fernet_key(self._fingerprint)
        self._fernet: Any = None
        if _HAS_CRYPTOGRAPHY:
            self._fernet = Fernet(self._fernet_key)

        self._cache: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    @property
    def path(self) -> Path:
        """存储文件路径。"""
        return self._path

    def load(self) -> None:
        """从磁盘加载 API Key 到内存缓存和环境变量。

        如果文件不存在则初始化空缓存。
        """
        if not self._path.exists():
            self._cache = {}
            self._loaded = True
            return

        try:
            raw = self._read_file()
            data = json.loads(raw)
            self._cache = data.get("keys", {})

            # 解密并注入环境变量
            for env_var, entry in self._cache.items():
                try:
                    value = self._decrypt(entry.get("encrypted_value", ""))
                    if value:
                        os.environ[env_var] = value
                except Exception as e:
                    log.warning("加载 API Key %s 失败: %s", env_var, e)

            self._loaded = True
            log.info("已加载 %d 个 API Key 到环境变量", len(self._cache))
        except Exception as e:
            log.error("加载 API Key 存储文件失败: %s", e)
            self._cache = {}
            self._loaded = True

    def save(self) -> None:
        """将内存缓存中的 API Key 加密保存到磁盘。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": 1,
            "keys": self._cache,
            "updated_at": time.time(),
            "fingerprint_hash": hashlib.sha256(self._fingerprint.encode()).hexdigest()[:16],
        }

        raw = json.dumps(data, ensure_ascii=False, indent=2)
        self._write_file(raw)

        # 设置文件权限 (仅限当前用户读写)
        try:
            self._set_secure_permissions()
        except Exception as e:
            log.debug("忽略预期内异常: %s", e, exc_info=True)

        log.info("已保存 %d 个 API Key 到 %s", len(self._cache), self._path)

    def set_key(self, env_var: str, value: str, provider: str = "") -> Dict[str, Any]:
        """设置一个 API Key。

        Args:
            env_var: 环境变量名 (如 "DEEPSEEK_API_KEY")。
            value: API Key 明文。
            provider: 提供商标识符 (如 "deepseek")。

        Returns:
            操作结果字典。
        """
        if not env_var:
            return {"ok": False, "error": "缺少 env_var 参数"}

        if value:
            encrypted = self._encrypt(value)
            self._cache[env_var] = {
                "encrypted_value": encrypted,
                "provider": provider,
                "updated_at": time.time(),
            }
            os.environ[env_var] = value
            log.info("API Key 已设置: %s (长度=%d)", env_var, len(value))
        else:
            # 空值相当于删除
            self.remove_key(env_var)
            return {"ok": True, "removed": True, "env_var": env_var}

        self.save()

        return {
            "ok": True,
            "env_var": env_var,
            "provider": provider,
            "key_length": len(value),
            "masked_preview": self._mask(value),
        }

    def get_key_meta(self, env_var: str) -> Optional[Dict[str, Any]]:
        """获取指定 API Key 的元信息 (不返回明文)。

        Args:
            env_var: 环境变量名。

        Returns:
            元信息字典或 None。
        """
        entry = self._cache.get(env_var)
        if not entry:
            return None

        # 从环境变量获取当前值来计算脱敏预览
        current_val = os.environ.get(env_var, "")
        return {
            "env_var": env_var,
            "provider": entry.get("provider", ""),
            "has_key": bool(current_val),
            "key_length": len(current_val) if current_val else 0,
            "masked_preview": self._mask(current_val) if current_val else "",
            "updated_at": entry.get("updated_at"),
        }

    def list_keys(self) -> Dict[str, Dict[str, Any]]:
        """列出所有已存储的 API Key 元信息。

        Returns:
            以 env_var 为键的元信息字典。
        """
        result = {}
        # 合并环境变量中存在但存储文件中没有的 key
        all_vars = set(self._cache.keys())
        for env_var in all_vars:
            meta = self.get_key_meta(env_var)
            if meta:
                result[env_var] = meta

        return result

    def remove_key(self, env_var: str) -> Dict[str, Any]:
        """删除一个 API Key。

        Args:
            env_var: 环境变量名。

        Returns:
            操作结果字典。
        """
        removed_from_cache = self._cache.pop(env_var, None)
        removed_from_env = os.environ.pop(env_var, None)

        if removed_from_cache:
            self.save()
            log.info("API Key 已删除: %s", env_var)

        return {
            "ok": True,
            "env_var": env_var,
            "was_in_cache": removed_from_cache is not None,
            "was_in_env": removed_from_env is not None,
        }

    def clear_all(self) -> Dict[str, Any]:
        """清空所有已存储的 API Key。

        Returns:
            操作结果字典。
        """
        count = len(self._cache)
        for env_var in list(self._cache.keys()):
            os.environ.pop(env_var, None)
        self._cache.clear()
        self.save()
        log.info("已清空所有 API Key (共 %d 个)", count)
        return {"ok": True, "cleared_count": count}

    def key_count(self) -> int:
        """返回已存储的 API Key 数量。"""
        return len(self._cache)

    def sync_to_environment(self) -> int:
        """将存储的 API Key 同步到 os.environ。

        Returns:
            成功同步的数量。
        """
        synced = 0
        for env_var, entry in self._cache.items():
            try:
                value = self._decrypt(entry.get("encrypted_value", ""))
                if value:
                    os.environ[env_var] = value
                    synced += 1
            except Exception as e:
                log.warning("同步 API Key %s 到环境变量失败: %s", env_var, e)
        return synced

    # ---- 加密/解密 ----

    def _encrypt(self, plaintext: str) -> str:
        """加密明文。

        Args:
            plaintext: 要加密的字符串。

        Returns:
            加密后的字符串。
        """
        if _HAS_CRYPTOGRAPHY and self._fernet:
            return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
        return _simple_encrypt(plaintext, self._fingerprint)

    def _decrypt(self, ciphertext: str) -> str:
        """解密密文。

        Args:
            ciphertext: 加密的字符串。

        Returns:
            解密后的明文。
        """
        if not ciphertext:
            return ""
        value = ""
        if _HAS_CRYPTOGRAPHY and self._fernet:
            try:
                return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
            except (InvalidToken, Exception):
                log.warning("Fernet 解密失败，尝试回退方案")
                value = _simple_decrypt(ciphertext, self._fingerprint)
        else:
            value = _simple_decrypt(ciphertext, self._fingerprint)
        if not value:
            log.error("API Key 解密失败（存储文件 %s），该 Key 不会被加载", self._path)
        return value

    # ---- 文件读写 ----

    def _read_file(self) -> str:
        """读取存储文件内容。

        Returns:
            文件内容字符串。
        """
        return self._path.read_text(encoding="utf-8")

    def _write_file(self, content: str) -> None:
        """写入存储文件内容。

        Args:
            content: 要写入的内容。
        """
        self._path.write_text(content, encoding="utf-8")

    def _set_secure_permissions(self) -> None:
        """设置文件权限为仅当前用户可读写。"""
        if os.name == "nt":
            # Windows: 使用 ACL 限制权限
            import subprocess
            try:
                subprocess.run(
                    ["icacls", str(self._path), "/inheritance:r", "/grant:r",
                     f"{os.environ.get('USERNAME', 'SYSTEM')}:(R,W)"],
                    capture_output=True, timeout=5
                )
            except Exception as e:
                log.debug("忽略预期内异常: %s", e, exc_info=True)
        else:
            # Unix: chmod 600
            self._path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    @staticmethod
    def _mask(value: str) -> str:
        """将 API Key 脱敏显示。

        Args:
            value: 原始密钥。

        Returns:
            脱敏后的字符串，如 sk-****abcd。
        """
        if not value:
            return ""
        if len(value) <= 8:
            return value[:2] + "*" * max(0, len(value) - 4) + value[-2:]
        return value[:4] + "****" + value[-4:]


def create_api_key_store(home_path: Optional[str | Path] = None) -> ApiKeyStore:
    """创建并初始化 API Key 存储实例。

    Args:
        home_path: 存储目录路径，默认 ~/.aivyos/

    Returns:
        已加载的 ApiKeyStore 实例。
    """
    if home_path:
        home = Path(home_path)
        if home.is_dir() or home.suffix == "":
            storage_path = home / "api_keys.enc"
        else:
            storage_path = home
    else:
        home = Path(os.environ.get("AIVYOS_HOME", Path.home() / ".aivyos"))
        storage_path = home / "api_keys.enc"

    store = ApiKeyStore(storage_path=storage_path)
    store.load()
    return store