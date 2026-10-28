"""Passwords, temporary passwords, opaque tokens and access JWTs (ARCHITECTURE.md §7)."""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=30)
TEMP_PASSWORD_TTL = timedelta(days=7)
JWT_ALGORITHM = "HS256"
MIN_PASSWORD_LENGTH = 10

SubjectType = Literal["user", "platform_user"]

_hasher = PasswordHasher()  # Argon2id with library defaults (RFC 9106 low-memory profile)

# Readable alphabet for temporary passwords shared by phone/WhatsApp: no 0/O, 1/l/I.
_TEMP_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# Rejected outright; a breached-password list check is added with the auth service.
_COMMON_PASSWORDS = frozenset(
    {"password", "password1", "password123", "1234567890", "qwertyuiop", "iloveyou12", "nepal12345", "admin12345"}
)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_problems(password: str, *, email: str | None = None) -> list[str]:
    """Policy from ONBOARDING_AND_CHANNEL_SETUP.md §3.3: length + not common. No complexity rules."""
    problems: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    lowered = password.lower()
    if lowered in _COMMON_PASSWORDS:
        problems.append("This password is too common.")
    if email and lowered == email.lower().split("@")[0]:
        problems.append("Do not use your email name as the password.")
    return problems


def generate_temporary_password() -> str:
    """14 readable characters in groups, e.g. ``Kq7m-Rt4x-Wp9z`` (12 random chars, ~69 bits)."""
    groups = ["".join(secrets.choice(_TEMP_ALPHABET) for _ in range(4)) for _ in range(3)]
    return "-".join(groups)


def generate_opaque_token() -> str:
    """256-bit random token for refresh, reset and verification links. Only its hash is stored."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


@dataclass(frozen=True)
class AccessClaims:
    subject_id: uuid.UUID
    subject_type: SubjectType
    session_id: uuid.UUID  # refresh-token family; revoking it ends the session
    tenant_id: uuid.UUID | None
    expires_at: datetime


def create_access_token(
    *,
    subject_id: uuid.UUID,
    subject_type: SubjectType,
    session_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    now: datetime | None = None,
) -> str:
    issued = now or datetime.now(UTC)
    payload = {
        "sub": str(subject_id),
        "typ": subject_type,
        "sid": str(session_id),
        "tid": str(tenant_id) if tenant_id else None,
        "iat": int(issued.timestamp()),
        "exp": int((issued + ACCESS_TOKEN_TTL).timestamp()),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm=JWT_ALGORITHM)


class InvalidAccessToken(Exception):
    pass


def decode_access_token(token: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "typ", "sid", "exp", "iat"]},
        )
        subject_type = payload["typ"]
        if subject_type not in ("user", "platform_user"):
            raise InvalidAccessToken("unknown subject type")
        return AccessClaims(
            subject_id=uuid.UUID(payload["sub"]),
            subject_type=subject_type,
            session_id=uuid.UUID(payload["sid"]),
            tenant_id=uuid.UUID(payload["tid"]) if payload.get("tid") else None,
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise InvalidAccessToken(str(exc)) from exc
