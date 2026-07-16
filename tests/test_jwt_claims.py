"""JWT issuance and access-claims dependency contracts."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from jose import jwt

from app.auth.auth_handler import create_access_token, create_refresh_token
from app.auth.dependencies import get_current_token_claims
from app.config.settings import settings


SUBJECT = "550e8400-e29b-41d4-a716-446655440000"
SESSION_ID = "11111111-1111-1111-1111-111111111111"


def _decode(token):
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def test_new_tokens_have_required_claims_and_unique_jtis():
    first_access = _decode(create_access_token({"sub": SUBJECT}, session_id=SESSION_ID))
    second_access = _decode(
        create_access_token({"sub": SUBJECT}, session_id=SESSION_ID)
    )
    refresh = _decode(create_refresh_token({"sub": SUBJECT}, session_id=SESSION_ID))

    assert {"sub", "sid", "jti", "iat", "exp"} <= first_access.keys()
    assert first_access["sub"] == SUBJECT
    assert first_access["sid"] == SESSION_ID
    assert first_access["jti"] != second_access["jti"]
    assert "refresh" not in first_access
    assert {"sub", "sid", "jti", "iat", "exp", "refresh"} <= refresh.keys()
    assert refresh["refresh"] is True


def test_access_claims_dependency_returns_valid_claims_and_accepts_legacy_access():
    access = create_access_token({"sub": SUBJECT}, session_id=SESSION_ID)
    legacy = jwt.encode(
        {"sub": SUBJECT, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    claims = asyncio.run(get_current_token_claims(SimpleNamespace(), token=access))
    legacy_claims = asyncio.run(
        get_current_token_claims(SimpleNamespace(), token=legacy)
    )

    assert claims["sub"] == SUBJECT
    assert claims["sid"] == SESSION_ID
    assert claims["jti"] is not None
    assert isinstance(claims["iat"], int)
    assert legacy_claims == {"sub": SUBJECT, "sid": None, "jti": None, "iat": None}


@pytest.mark.parametrize(
    "token",
    [
        create_refresh_token({"sub": SUBJECT}, session_id=SESSION_ID),
        jwt.encode(
            {"sub": SUBJECT, "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
        ),
    ],
    ids=["refresh-token", "expired-token"],
)
def test_access_claims_dependency_rejects_refresh_and_expired_tokens(token):
    with pytest.raises(HTTPException) as error:
        asyncio.run(get_current_token_claims(SimpleNamespace(), token=token))

    assert error.value.status_code == 401
