"""Application-level encryption for credentials (ARCHITECTURE.md §13).

AES-256-GCM, random 96-bit nonce per value, caller-supplied associated data (AAD)
binding the ciphertext to its row (e.g. ``tenant_id|credential_id``) so a blob copied
into another row fails to decrypt. Keys are versioned for rotation; the newest key
encrypts, any configured key decrypts.

MVP keys come from ``ENCRYPTION_KEYS`` (``v1:<base64>,v2:<base64>``). A KMS-backed
provider can implement :class:`KeyProvider` later without changing stored blobs' shape.
"""

import base64
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_NONCE_BYTES = 12


class DecryptionError(Exception):
    pass


@dataclass(frozen=True)
class EncryptedBlob:
    key_version: int
    nonce: bytes
    ciphertext: bytes


class KeyProvider(Protocol):
    def current_version(self) -> int: ...
    def key(self, version: int) -> bytes: ...


class EnvKeyProvider:
    def __init__(self, spec: str) -> None:
        self._keys: dict[int, bytes] = {}
        for item in filter(None, (part.strip() for part in spec.split(","))):
            label, _, encoded = item.partition(":")
            if not label.startswith("v") or not label[1:].isdigit():
                raise ValueError("ENCRYPTION_KEYS entries must look like v1:<base64>")
            key = base64.b64decode(encoded, validate=True)
            if len(key) != 32:
                raise ValueError(f"encryption key {label} must be 32 bytes")
            self._keys[int(label[1:])] = key
        if not self._keys:
            raise ValueError("ENCRYPTION_KEYS is empty")

    def current_version(self) -> int:
        return max(self._keys)

    def key(self, version: int) -> bytes:
        try:
            return self._keys[version]
        except KeyError as exc:
            raise DecryptionError(f"unknown key version {version}") from exc


@lru_cache
def default_key_provider() -> KeyProvider:
    return EnvKeyProvider(get_settings().encryption_keys)


def encrypt(plaintext: bytes, aad: bytes, provider: KeyProvider | None = None) -> EncryptedBlob:
    keys = provider or default_key_provider()
    version = keys.current_version()
    nonce = os.urandom(_NONCE_BYTES)
    return EncryptedBlob(version, nonce, AESGCM(keys.key(version)).encrypt(nonce, plaintext, aad))


def decrypt(blob: EncryptedBlob, aad: bytes, provider: KeyProvider | None = None) -> bytes:
    keys = provider or default_key_provider()
    try:
        return AESGCM(keys.key(blob.key_version)).decrypt(blob.nonce, blob.ciphertext, aad)
    except InvalidTag as exc:
        raise DecryptionError("ciphertext or associated data does not match") from exc
