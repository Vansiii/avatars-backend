"""Rate-limit middleware contracts for PR2b."""

import asyncio
from unittest.mock import AsyncMock

from fastapi import FastAPI
from jose import jwt
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config.settings import settings
from app.middleware.rate_limit import (
    LocalWindowLimiter,
    RATE_LIMIT_LUA,
    RateLimitMiddleware,
)


def make_request(
    app, *, path="/", method="GET", headers=None, client=("192.168.1.50", 1234)
):
    raw_headers = [
        (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": raw_headers,
            "client": client,
            "app": app,
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


async def ok_response(_request):
    return JSONResponse({"ok": True})


class CountingRedis:
    def __init__(self):
        self.counts = {}
        self.script_load = AsyncMock(return_value="rate-limit-sha")
        self.calls = []

    async def evalsha(self, sha, numkeys, key, limit, ttl):
        self.calls.append((sha, numkeys, key, limit, ttl))
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


class MockRedis(CountingRedis):
    """Small Redis-script model that preserves first-write expiry semantics."""

    def __init__(self):
        super().__init__()
        self._data = {}
        self.now = 0

    async def evalsha(self, sha, numkeys, key, limit, ttl):
        self.calls.append((sha, numkeys, key, limit, ttl))
        entry = self._data.get(key)
        if entry is None or entry["expires_at"] <= self.now:
            entry = {"count": 0, "expires_at": self.now + ttl}
            self._data[key] = entry
        entry["count"] += 1
        return entry["count"]


def healthy_app(redis):
    app = FastAPI()
    app.state.redis = redis
    app.state.degraded = False
    return app


def test_local_window_limiter_evicts_old_windows_and_can_clear():
    limiter = LocalWindowLimiter(max_entries=2)

    assert limiter.check_and_increment("general:a", 10, 100) == 1
    assert limiter.check_and_increment("general:a", 10, 100) == 2
    assert limiter.check_and_increment("general:b", 10, 99) == 1
    assert limiter.check_and_increment("general:c", 10, 100) == 1
    assert set(limiter._buckets) == {("general:a", 100), ("general:c", 100)}

    limiter.clear()
    assert limiter._buckets == {}


def test_redis_lua_counter_loads_once_and_sets_standard_headers(monkeypatch):
    redis = CountingRedis()
    app = healthy_app(redis)
    middleware = RateLimitMiddleware(app, general_per_minute=3, generation_per_minute=2)
    monkeypatch.setattr("app.middleware.rate_limit.time.time", lambda: 121.7)

    response = asyncio.run(middleware.dispatch(make_request(app), ok_response))

    assert redis.script_load.await_count == 1
    assert redis.script_load.await_args.args == (RATE_LIMIT_LUA,)
    assert redis.calls == [
        ("rate-limit-sha", 1, "ratelimit:v1:general:ip:192.168.1.50:2", 3, 59)
    ]
    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "3"
    assert response.headers["X-RateLimit-Remaining"] == "2"


def test_redis_counter_preserves_first_write_ttl_and_starts_after_expiry(monkeypatch):
    redis = MockRedis()
    app = healthy_app(redis)
    middleware = RateLimitMiddleware(app, general_per_minute=3, generation_per_minute=2)
    monkeypatch.setattr("app.middleware.rate_limit.time.time", lambda: 121.7)
    request = make_request(app)

    asyncio.run(middleware.dispatch(request, ok_response))
    key = "ratelimit:v1:general:ip:192.168.1.50:2"
    initial_expiry = redis._data[key]["expires_at"]
    asyncio.run(middleware.dispatch(request, ok_response))

    assert redis._data[key] == {"count": 2, "expires_at": initial_expiry}
    redis.now = initial_expiry
    assert asyncio.run(middleware.increment_redis(redis, key, 3, 59)) == 1
    assert redis._data[key]["expires_at"] == initial_expiry + 59


def test_noscript_reloads_once_and_retries_evalsha(monkeypatch):
    from redis.exceptions import NoScriptError

    redis = CountingRedis()
    redis.script_load = AsyncMock(side_effect=["sha-before", "sha-after"])
    attempts = []

    async def evalsha(sha, numkeys, key, limit, ttl):
        attempts.append(sha)
        if len(attempts) == 1:
            raise NoScriptError("NOSCRIPT")
        return 1

    redis.evalsha = evalsha
    app = healthy_app(redis)
    middleware = RateLimitMiddleware(app, general_per_minute=3, generation_per_minute=2)
    monkeypatch.setattr("app.middleware.rate_limit.time.time", lambda: 120.0)

    response = asyncio.run(middleware.dispatch(make_request(app), ok_response))

    assert response.status_code == 200
    assert attempts == ["sha-before", "sha-after"]
    assert redis.script_load.await_count == 2


def test_generation_limit_is_independent_but_consumes_general_counter(monkeypatch):
    redis = CountingRedis()
    app = healthy_app(redis)
    middleware = RateLimitMiddleware(app, general_per_minute=3, generation_per_minute=1)
    monkeypatch.setattr("app.middleware.rate_limit.time.time", lambda: 120.0)
    request = make_request(app, path="/api/v1/generations", method="POST")

    first = asyncio.run(middleware.dispatch(request, ok_response))
    second = asyncio.run(middleware.dispatch(request, ok_response))

    assert first.status_code == 200
    assert second.status_code == 429
    assert (
        second.body
        == b'{"detail":"Demasiadas solicitudes. Por favor intenta nuevamente en un minuto."}'
    )
    assert second.headers["X-RateLimit-Remaining"] == "0"
    assert second.headers["Retry-After"] == "60"
    assert redis.counts["ratelimit:v1:general:ip:192.168.1.50:2"] == 2
    assert redis.counts["ratelimit:v1:generation:ip:192.168.1.50:2"] == 2


def test_degraded_mode_uses_local_limiter_without_shared_state_headers(monkeypatch):
    app = FastAPI()
    app.state.redis = None
    app.state.degraded = True
    middleware = RateLimitMiddleware(app, general_per_minute=1, generation_per_minute=1)
    monkeypatch.setattr("app.middleware.rate_limit.time.time", lambda: 120.0)

    first = asyncio.run(middleware.dispatch(make_request(app), ok_response))
    second = asyncio.run(middleware.dispatch(make_request(app), ok_response))

    assert first.status_code == 200
    assert "X-RateLimit-Limit" not in first.headers
    assert second.status_code == 429
    assert "X-RateLimit-Limit" not in second.headers
    assert "Retry-After" not in second.headers


def test_redis_failure_enters_degraded_mode_and_uses_local_limit(monkeypatch):
    redis = CountingRedis()

    async def unavailable(*_args):
        raise OSError("redis unavailable")

    redis.evalsha = unavailable
    app = healthy_app(redis)
    middleware = RateLimitMiddleware(app, general_per_minute=1, generation_per_minute=1)
    monkeypatch.setattr("app.middleware.rate_limit.time.time", lambda: 120.0)

    first = asyncio.run(middleware.dispatch(make_request(app), ok_response))
    second = asyncio.run(middleware.dispatch(make_request(app), ok_response))

    assert first.status_code == 200
    assert app.state.degraded is True
    assert app.state.redis is None
    assert "X-RateLimit-Limit" not in first.headers
    assert second.status_code == 429
    assert "Retry-After" not in second.headers


def test_exempt_paths_skip_counters_and_headers():
    redis = CountingRedis()
    app = healthy_app(redis)
    middleware = RateLimitMiddleware(app, general_per_minute=1, generation_per_minute=1)

    response = asyncio.run(
        middleware.dispatch(make_request(app, path="/health"), ok_response)
    )

    assert response.status_code == 200
    assert redis.script_load.await_count == 0
    assert "X-RateLimit-Limit" not in response.headers


def test_identity_uses_valid_access_token_or_configured_client_address(monkeypatch):
    app = healthy_app(CountingRedis())
    middleware = RateLimitMiddleware(app, general_per_minute=1, generation_per_minute=1)
    token = jwt.encode(
        {"sub": "user-123"}, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )

    assert (
        middleware.resolve_identity(
            make_request(app, headers={"Authorization": f"Bearer {token}"})
        )
        == "user:user-123"
    )

    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    assert (
        middleware.resolve_identity(
            make_request(app, headers={"X-Forwarded-For": "10.0.0.1, 172.16.0.1"})
        )
        == "ip:10.0.0.1"
    )

    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
    assert (
        middleware.resolve_identity(
            make_request(
                app, headers={"X-Forwarded-For": "10.0.0.1"}, client=("192.168.1.50", 1)
            )
        )
        == "ip:192.168.1.50"
    )
