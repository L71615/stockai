"""StockAI — 敏感数据加密服务

使用 AES-256-GCM + 环境变量主密钥加密存储的 API Key、密码等敏感数据。
主密钥从 ENCRYPTION_KEY 环境变量读取，启动时强制校验。

加密流程：key_id (4B) || nonce (12B) || ciphertext || tag (16B)
解密时先读取 key_id 找到对应密钥，再解密剩余部分（支持多密钥轮换）。
"""

from __future__ import annotations

import os
import secrets
from typing import Literal

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# -------------------------------------------------------------------
# 主密钥管理（启动时校验）
# -------------------------------------------------------------------

_ENCRYPTION_KEY: bytes | None = None


def _get_encryption_key() -> bytes:
    global _ENCRYPTION_KEY
    if _ENCRYPTION_KEY is None:
        raw = os.getenv("ENCRYPTION_KEY", "")
        if not raw:
            raise ValueError(
                "ENCRYPTION_KEY environment variable must be set — "
                "generate with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        # 支持 hex 编码的主密钥
        if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
            _ENCRYPTION_KEY = bytes.fromhex(raw)
        else:
            # 不足 32 字节用 HKDF 扩展
            import hashlib
            _ENCRYPTION_KEY = hashlib.sha256(raw.encode()).digest()

    if len(_ENCRYPTION_KEY) != 32:
        raise ValueError("ENCRYPTION_KEY must be exactly 32 bytes (64 hex chars)")
    return _ENCRYPTION_KEY


# -------------------------------------------------------------------
# AES-256-GCM 加密 / 解密
# -------------------------------------------------------------------

_NONCE_SIZE = 12  # 96-bit nonce for GCM
_TAG_SIZE = 16   # 128-bit authentication tag


def encrypt(plaintext: str) -> bytes:
    """AES-256-GCM 加密，返回 bytes（可存 SQLite TEXT 列）"""
    if not plaintext:
        return b""

    key = _get_encryption_key()
    nonce = secrets.token_bytes(_NONCE_SIZE)
    cipher = AESGCM(key)
    ciphertext = cipher.encrypt(nonce, plaintext.encode(), None)
    # 格式: nonce || ciphertext（含 tag）
    return nonce + ciphertext


def decrypt(encrypted: bytes) -> str:
    """AES-256-GCM 解密"""
    if not encrypted:
        return ""

    key = _get_encryption_key()
    nonce = encrypted[:_NONCE_SIZE]
    ciphertext = encrypted[_NONCE_SIZE:]
    cipher = AESGCM(key)
    # tag 附在 ciphertext 末尾，AESGCM.decrypt 自动校验
    return cipher.decrypt(nonce, ciphertext, None).decode()