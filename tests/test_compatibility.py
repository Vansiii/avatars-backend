"""Backward-compatible API contracts retained by PR2 session controls."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.v1.auth import router as auth_router
from app.auth.dependencies import get_current_user
from app.main import app
from app.schemas.user import Token


def test_health_is_rate_limit_exempt_without_rate_limit_headers():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0"}
    assert "x-ratelimit-limit" not in response.headers
    assert "x-ratelimit-remaining" not in response.headers


def test_login_and_refresh_retain_the_original_token_response_schema():
    response_fields = set(Token.model_fields)
    token_routes = {
        route.path: route.response_model
        for route in auth_router.routes
        if route.path in {"/auth/login", "/auth/refresh"}
    }

    assert response_fields == {"access_token", "refresh_token", "token_type"}
    assert token_routes == {"/auth/login": Token, "/auth/refresh": Token}


def test_legacy_access_claims_skip_redis_blacklist_lookup():
    user = SimpleNamespace(id="legacy-user", is_active=True)
    query = SimpleNamespace(
        filter=lambda *_conditions: SimpleNamespace(first=lambda: user)
    )
    database = SimpleNamespace(query=lambda *_model: query)
    redis = SimpleNamespace(
        get=AsyncMock(side_effect=AssertionError("must not be called"))
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(degraded=False, redis=redis))
    )

    result = asyncio.run(
        get_current_user(
            request,
            {"sub": "legacy-user", "sid": None, "jti": None, "iat": None},
            database,
        )
    )

    assert result is user
    assert redis.get.await_count == 0
