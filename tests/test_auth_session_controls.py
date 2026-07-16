"""JWT claim and session-control authentication contracts."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from fastapi import HTTPException
from jose import jwt

from app.auth.auth_handler import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
)
from app.api.v1 import auth
from app.auth import dependencies
from app.auth.dependencies import get_current_token_claims, get_current_user
from app.config.settings import settings
from app.models.refresh_token import RefreshToken
from app.models.session import Session as AuthSession
from app.models.user import User
from app.schemas.user import UserLogin


def test_new_access_tokens_include_session_claims_and_never_refresh_flag():
    token = create_access_token(
        {"sub": "550e8400-e29b-41d4-a716-446655440000", "jti": "caller-value"},
        session_id="11111111-1111-1111-1111-111111111111",
        expires_delta=timedelta(minutes=5),
    )

    claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

    assert claims["sub"] == "550e8400-e29b-41d4-a716-446655440000"
    assert claims["sid"] == "11111111-1111-1111-1111-111111111111"
    assert UUID(claims["jti"])
    assert claims["jti"] != "caller-value"
    assert isinstance(claims["iat"], int)
    assert "refresh" not in claims


def test_refresh_tokens_have_unique_jtis_refresh_flag_and_sha256_hash():
    first = create_refresh_token(
        {"sub": "550e8400-e29b-41d4-a716-446655440000"},
        session_id="11111111-1111-1111-1111-111111111111",
        expires_delta=timedelta(days=1),
    )
    second = create_refresh_token(
        {"sub": "550e8400-e29b-41d4-a716-446655440000"},
        session_id="11111111-1111-1111-1111-111111111111",
        expires_delta=timedelta(days=1),
    )

    first_claims = jwt.decode(
        first, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
    )
    second_claims = jwt.decode(
        second, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
    )

    assert first_claims["refresh"] is True
    assert first_claims["sid"] == "11111111-1111-1111-1111-111111111111"
    assert UUID(first_claims["jti"])
    assert first_claims["jti"] != second_claims["jti"]
    assert (
        hash_refresh_token(first)
        == __import__("hashlib").sha256(first.encode("utf-8")).hexdigest()
    )


def test_claims_dependency_returns_legacy_claims_and_rejects_refresh_tokens():
    access_token = jwt.encode(
        {
            "sub": "550e8400-e29b-41d4-a716-446655440000",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    refresh_token = create_refresh_token(
        {"sub": "550e8400-e29b-41d4-a716-446655440000"},
        expires_delta=timedelta(minutes=5),
    )

    claims = asyncio.run(
        get_current_token_claims(SimpleNamespace(), token=access_token)
    )

    assert claims == {
        "sub": "550e8400-e29b-41d4-a716-446655440000",
        "sid": None,
        "jti": None,
        "iat": None,
    }
    with pytest.raises(HTTPException) as error:
        asyncio.run(get_current_token_claims(SimpleNamespace(), token=refresh_token))
    assert error.value.status_code == 401


def test_current_user_rejects_redis_blacklist_before_database_query():
    db = Mock()
    redis = SimpleNamespace(get=AsyncMock(return_value=b"1"))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(degraded=False, redis=redis))
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            get_current_user(
                request,
                claims={"sub": "user-1", "sid": "sid-1", "jti": None, "iat": None},
                db=db,
            )
        )

    assert error.value.status_code == 401
    db.query.assert_not_called()


def test_current_user_accepts_legacy_token_without_redis_or_session_query():
    user = SimpleNamespace(id="user-1", is_active=True)
    query = SimpleNamespace(filter=lambda *_args: SimpleNamespace(first=lambda: user))
    db = SimpleNamespace(query=lambda *_args: query)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(degraded=False, redis=None))
    )

    result = asyncio.run(
        get_current_user(
            request,
            claims={"sub": "user-1", "sid": None, "jti": None, "iat": None},
            db=db,
        )
    )

    assert result is user


def test_current_user_falls_back_to_pg_when_redis_read_fails(monkeypatch):
    user = SimpleNamespace(id="user-1", is_active=True)
    redis = SimpleNamespace(get=AsyncMock(side_effect=RuntimeError("unavailable")))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(degraded=False, redis=redis))
    )
    check_session_pg = AsyncMock(return_value=user)
    monkeypatch.setattr(dependencies, "_check_session_pg", check_session_pg)

    result = asyncio.run(
        get_current_user(
            request,
            claims={"sub": "user-1", "sid": "sid-1", "jti": None, "iat": None},
            db=Mock(),
        )
    )

    assert result is user
    assert request.app.state.degraded is True
    check_session_pg.assert_awaited_once()


class _AuthQuery:
    def __init__(self, result, update_count=1):
        self.result = result
        self.update_count = update_count
        self.updated_values = None

    def filter(self, *_conditions):
        return self

    def first(self):
        return self.result

    def update(self, values, **_kwargs):
        self.updated_values = values
        return self.update_count


class _AuthDatabase:
    def __init__(self, user, refresh_token=None, session=None, update_count=1):
        self.user = user
        self.refresh_token = refresh_token
        self.session = session
        self.update_count = update_count
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def query(self, model):
        if model is User:
            return _AuthQuery(self.user, self.update_count)
        if model is RefreshToken:
            return _AuthQuery(self.refresh_token, self.update_count)
        if model is AuthSession:
            return _AuthQuery(self.session, self.update_count)
        return _AuthQuery(None, self.update_count)

    def add(self, instance):
        self.added.append(instance)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _request(*, degraded=False, redis=None):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(degraded=degraded, redis=redis))
    )


def _active_user():
    return SimpleNamespace(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="user@example.com",
        hashed_password="hash",
        is_active=True,
    )


def test_login_persists_only_refresh_hash_and_uses_degraded_access_ttl(monkeypatch):
    user = _active_user()
    db = _AuthDatabase(user)
    monkeypatch.setattr(auth, "verify_password", lambda *_args: True)

    response = asyncio.run(
        auth.login(
            UserLogin(email=user.email, password="Password1"),
            _request(degraded=True),
            db,
        )
    )

    access_claims = jwt.decode(
        response["access_token"], settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
    )
    refresh_claims = jwt.decode(
        response["refresh_token"], settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
    )
    session = next(item for item in db.added if isinstance(item, AuthSession))
    refresh_record = next(item for item in db.added if isinstance(item, RefreshToken))

    assert response["token_type"] == "bearer"
    assert access_claims["sid"] == refresh_claims["sid"] == str(session.sid)
    assert access_claims["exp"] - access_claims["iat"] == 120
    assert refresh_record.token_hash == hash_refresh_token(response["refresh_token"])
    assert response["refresh_token"] not in vars(refresh_record).values()
    assert session.refresh_token_hash == refresh_record.token_hash
    assert db.commits == 1


def test_refresh_rotation_replaces_old_hash_and_rejects_replay(monkeypatch):
    user = _active_user()
    sid = "11111111-1111-1111-1111-111111111111"
    presented = create_refresh_token({"sub": user.id}, session_id=sid)
    old_token = SimpleNamespace(id="old-id", user_id=user.id, session_id=sid)
    active_session = SimpleNamespace(sid=sid, user_id=user.id)
    db = _AuthDatabase(user, refresh_token=old_token, session=active_session)

    response = asyncio.run(
        auth.refresh_token(
            auth.RefreshTokenRequest(refresh_token=presented), _request(), db
        )
    )

    successor = next(item for item in db.added if isinstance(item, RefreshToken))
    assert response["token_type"] == "bearer"
    assert successor.token_hash == hash_refresh_token(response["refresh_token"])
    assert db.commits == 1

    replay_db = _AuthDatabase(
        user, refresh_token=old_token, session=active_session, update_count=0
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            auth.refresh_token(
                auth.RefreshTokenRequest(refresh_token=presented), _request(), replay_db
            )
        )
    assert error.value.status_code == 401
    assert replay_db.rollbacks == 1


def test_legacy_refresh_creates_tombstone_and_logout_projects_blacklist(monkeypatch):
    user = _active_user()
    legacy_token = jwt.encode(
        {
            "sub": user.id,
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "refresh": True,
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    db = _AuthDatabase(user, refresh_token=None)

    response = asyncio.run(
        auth.refresh_token(
            auth.RefreshTokenRequest(refresh_token=legacy_token), _request(), db
        )
    )

    records = [item for item in db.added if isinstance(item, RefreshToken)]
    tombstone = next(record for record in records if record.revoked is True)
    successor = next(record for record in records if record.revoked is not True)
    assert tombstone.token_hash == hash_refresh_token(legacy_token)
    assert tombstone.replaced_by == successor.id

    redis = SimpleNamespace(set=AsyncMock())
    logout_db = _AuthDatabase(user, refresh_token=successor, session=SimpleNamespace())
    result = asyncio.run(
        auth.logout(
            _request(redis=redis),
            {"sub": user.id, "sid": str(successor.session_id), "exp": 2**31},
            logout_db,
            auth.LogoutRequest(refresh_token=response["refresh_token"]),
        )
    )

    assert result == {"message": "Sesión cerrada correctamente"}
    assert logout_db.commits == 1
    redis.set.assert_awaited_once()
