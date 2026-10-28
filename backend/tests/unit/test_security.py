import base64
import os
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core import crypto, security


def test_password_hash_roundtrip() -> None:
    hashed = security.hash_password("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert security.verify_password(hashed, "correct horse battery")
    assert not security.verify_password(hashed, "wrong password")


def test_verify_password_handles_garbage_hash() -> None:
    assert not security.verify_password("not-a-hash", "anything")


@pytest.mark.parametrize(
    ("password", "ok"),
    [("short", False), ("password123", False), ("ram.sharma", False), ("a long enough passphrase", True)],
)
def test_password_policy(password: str, ok: bool) -> None:
    assert (security.password_problems(password, email="ram.sharma@example.com") == []) is ok


def test_temporary_password_is_readable_and_random() -> None:
    passwords = {security.generate_temporary_password() for _ in range(200)}
    assert len(passwords) == 200
    for pw in passwords:
        assert len(pw) == 14 and pw.count("-") == 2
        assert not set(pw) & set("0O1lI")


def test_token_hash_is_stable_and_not_the_token() -> None:
    token = security.generate_opaque_token()
    assert security.hash_token(token) == security.hash_token(token)
    assert token not in security.hash_token(token)
    assert len(token) >= 43


def test_access_token_roundtrip() -> None:
    user, session, tenant = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    token = security.create_access_token(subject_id=user, subject_type="user", session_id=session, tenant_id=tenant)
    claims = security.decode_access_token(token)
    assert (claims.subject_id, claims.session_id, claims.tenant_id, claims.subject_type) == (
        user,
        session,
        tenant,
        "user",
    )


def test_expired_access_token_rejected() -> None:
    token = security.create_access_token(
        subject_id=uuid.uuid4(),
        subject_type="user",
        session_id=uuid.uuid4(),
        tenant_id=None,
        now=datetime.now(UTC) - timedelta(hours=1),
    )
    with pytest.raises(security.InvalidAccessToken):
        security.decode_access_token(token)


def test_tampered_and_unsigned_tokens_rejected() -> None:
    token = security.create_access_token(
        subject_id=uuid.uuid4(), subject_type="user", session_id=uuid.uuid4(), tenant_id=None
    )
    with pytest.raises(security.InvalidAccessToken):
        security.decode_access_token(token[:-2] + ("AA" if token[-2:] != "AA" else "BB"))
    unsigned = jwt.encode(
        {"sub": str(uuid.uuid4()), "typ": "user", "sid": str(uuid.uuid4())}, key=None, algorithm="none"
    )
    with pytest.raises(security.InvalidAccessToken):
        security.decode_access_token(unsigned)


def _keys(*versions: int) -> crypto.EnvKeyProvider:
    return crypto.EnvKeyProvider(",".join(f"v{v}:{base64.b64encode(os.urandom(32)).decode()}" for v in versions))


def test_encrypt_decrypt_roundtrip_with_aad() -> None:
    keys = _keys(1)
    blob = crypto.encrypt(b"EAAG-page-token", b"tenant|cred", keys)
    assert b"EAAG" not in blob.ciphertext
    assert crypto.decrypt(blob, b"tenant|cred", keys) == b"EAAG-page-token"


def test_decrypt_fails_with_wrong_aad() -> None:
    keys = _keys(1)
    blob = crypto.encrypt(b"secret", b"tenant-a|cred", keys)
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(blob, b"tenant-b|cred", keys)


def test_newest_key_encrypts_and_old_keys_still_decrypt() -> None:
    old = _keys(1)
    blob_v1 = crypto.encrypt(b"secret", b"aad", old)
    rotated = crypto.EnvKeyProvider(
        f"v1:{base64.b64encode(old.key(1)).decode()},v2:{base64.b64encode(os.urandom(32)).decode()}"
    )
    assert crypto.encrypt(b"x", b"aad", rotated).key_version == 2
    assert crypto.decrypt(blob_v1, b"aad", rotated) == b"secret"


@pytest.mark.parametrize("spec", ["", "v1:short", "key1:" + base64.b64encode(os.urandom(32)).decode()])
def test_invalid_key_spec_rejected(spec: str) -> None:
    with pytest.raises(ValueError):
        crypto.EnvKeyProvider(spec)
