"""Endpoint-level session lifecycle contracts using an isolated database boundary."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from jose import jwt

from app.api.v1 import auth
from app.auth.auth_handler import create_refresh_token, hash_refresh_token
from app.config.settings import settings
from app.models.refresh_token import RefreshToken
from app.models.session import Session
from app.models.user import User
from app.schemas.user import UserLogin


USER_ID = "550e8400-e29b-41d4-a716-446655440000"
SESSION_ID = "11111111-1111-1111-1111-111111111111"


class Query:
    def __init__(self, result, update_count=1):
        self.result = result
        self.update_count = update_count

    def filter(self, *_conditions):
        return self

    def first(self):
        return self.result

    def update(self, *_args, **_kwargs):
        return self.update_count


class Database:
    def __init__(self, user, refresh=None, session=None, update_count=1):
        self.user = user
        self.refresh = refresh
        self.session = session
        self.update_count = update_count
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def query(self, model):
        if model is User:
            return Query(self.user, self.update_count)
        if model is RefreshToken:
            return Query(self.refresh, self.update_count)
        if model is Session:
            return Query(self.session, self.update_count)
        return Query(None, self.update_count)

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def request(*, degraded=False, redis=None):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(degraded=degraded, redis=redis))
    )


def active_user():
    return SimpleNamespace(
        id=USER_ID,
        email="integration@example.com",
        hashed_password="hashed",
        is_active=True,
    )


def test_login_persists_session_and_hash_only_refresh_record(monkeypatch):
    database = Database(active_user())
    monkeypatch.setattr(auth, "verify_password", lambda *_args: True)

    response = asyncio.run(
        auth.login(
            UserLogin(email="integration@example.com", password="Password1"),
            request(),
            database,
        )
    )
    session = next(row for row in database.added if isinstance(row, Session))
    refresh = next(row for row in database.added if isinstance(row, RefreshToken))

    assert database.commits == 1
    assert refresh.token_hash == hash_refresh_token(response["refresh_token"])
    assert all(
        response["refresh_token"] not in vars(row).values() for row in database.added
    )
    assert session.refresh_token_hash == refresh.token_hash


def test_logout_is_pg_authoritative_when_redis_projection_fails():
    database = Database(active_user(), session=SimpleNamespace())
    redis = SimpleNamespace(set=AsyncMock(side_effect=OSError("unavailable")))

    response = asyncio.run(
        auth.logout(
            request(redis=redis),
            {"sub": USER_ID, "sid": SESSION_ID, "exp": 2**31},
            database,
        )
    )

    assert response == {"message": "Sesión cerrada correctamente"}
    assert database.commits == 1
    assert database.rollbacks == 0
    assert redis.set.await_count == 1


def test_logout_rejects_legacy_access_claims_without_a_session_id():
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            auth.logout(
                request(), {"sub": USER_ID, "sid": None}, Database(active_user())
            )
        )

    assert error.value.status_code == 401


def test_refresh_rejects_revoked_session_without_creating_successor():
    presented = create_refresh_token({"sub": USER_ID}, session_id=SESSION_ID)
    old_record = SimpleNamespace(id="old", user_id=USER_ID, session_id=SESSION_ID)
    database = Database(active_user(), refresh=old_record, session=None)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            auth.refresh_token(
                auth.RefreshTokenRequest(refresh_token=presented), request(), database
            )
        )

    assert error.value.status_code == 401
    assert database.added == []
    assert database.commits == 0


def test_concurrent_refresh_attempts_have_exactly_one_conditional_update_winner():
    class WinnerGate:
        available = True

        def update(self):
            if not self.available:
                return 0
            self.available = False
            return 1

    class AtomicQuery(Query):
        def update(self, *_args, **_kwargs):
            return gate.update()

    class AtomicDatabase(Database):
        def query(self, model):
            if model is RefreshToken:
                return AtomicQuery(self.refresh)
            return super().query(model)

    gate = WinnerGate()
    presented = create_refresh_token({"sub": USER_ID}, session_id=SESSION_ID)
    old_record = SimpleNamespace(id="old", user_id=USER_ID, session_id=SESSION_ID)
    active_session = SimpleNamespace(sid=SESSION_ID, user_id=USER_ID)
    winner = AtomicDatabase(active_user(), refresh=old_record, session=active_session)
    loser = AtomicDatabase(active_user(), refresh=old_record, session=active_session)

    winning_response = asyncio.run(
        auth.refresh_token(
            auth.RefreshTokenRequest(refresh_token=presented), request(), winner
        )
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            auth.refresh_token(
                auth.RefreshTokenRequest(refresh_token=presented), request(), loser
            )
        )

    assert winning_response["token_type"] == "bearer"
    assert winner.commits == 1
    assert error.value.status_code == 401
    assert loser.rollbacks == 1


def test_refresh_replay_logs_warning_without_raw_token_exposure(caplog):
    presented = create_refresh_token({"sub": USER_ID}, session_id=SESSION_ID)
    old_record = SimpleNamespace(id="old", user_id=USER_ID, session_id=SESSION_ID)
    active_session = SimpleNamespace(sid=SESSION_ID, user_id=USER_ID)
    database = Database(
        active_user(), refresh=old_record, session=active_session, update_count=0
    )

    with caplog.at_level(logging.WARNING, logger="app.api.v1.auth"):
        with pytest.raises(HTTPException):
            asyncio.run(
                auth.refresh_token(
                    auth.RefreshTokenRequest(refresh_token=presented),
                    request(),
                    database,
                )
            )

    assert "refresh token replay detected" in caplog.text.lower()
    assert presented not in caplog.text


def test_legacy_refresh_is_a_one_time_upgrade():
    legacy = jwt.encode(
        {
            "sub": USER_ID,
            "refresh": True,
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    tombstone = SimpleNamespace(token_hash=hash_refresh_token(legacy), revoked=True)
    database = Database(active_user(), refresh=tombstone)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            auth.refresh_token(
                auth.RefreshTokenRequest(refresh_token=legacy), request(), database
            )
        )

    assert error.value.status_code == 401
    assert database.added == []
