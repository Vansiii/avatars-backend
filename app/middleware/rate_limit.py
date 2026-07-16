"""Redis-backed fixed-window rate limiting with a bounded degraded fallback."""

import time
from typing import Any

from fastapi import Request
from jose import JWTError
from redis.exceptions import NoScriptError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.auth.auth_handler import decode_token
from app.config.settings import settings
from app.middleware.degraded import enter_degraded, is_degraded

RATE_LIMIT_LUA = """
-- KEYS[1] = redis key (e.g., ratelimit:v1:general:user:{uuid}:{window})
-- ARGV[1] = max requests per window
-- ARGV[2] = window TTL in seconds

local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return current
"""

_RATE_LIMITED_DETAIL = (
    "Demasiadas solicitudes. Por favor intenta nuevamente en un minuto."
)
_EXEMPT_PATHS = {"/docs", "/redoc", "/openapi.json", "/health"}


class LocalWindowLimiter:
    """Bounded per-process fallback for Redis-degraded operation."""

    def __init__(self, max_entries: int = 10000):
        self._buckets: dict[tuple[str, int], int] = {}
        self._max = max_entries

    def check_and_increment(self, key: str, limit: int, window_epoch: int) -> int:
        """Return the counter value after incrementing the fixed-window bucket."""
        bucket_key = (key, window_epoch)
        count = self._buckets.get(bucket_key, 0) + 1
        self._buckets[bucket_key] = count
        if len(self._buckets) > self._max:
            self._evict(window_epoch)
        return count

    def clear(self) -> None:
        self._buckets.clear()

    def _evict(self, current_window: int) -> None:
        self._buckets = {
            key: value
            for key, value in self._buckets.items()
            if key[1] == current_window
        }


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce shared Redis limits, falling back to local limits during outages."""

    def __init__(
        self,
        app: Any,
        *,
        general_per_minute: int = 100,
        generation_per_minute: int = 20,
    ) -> None:
        super().__init__(app)
        self.general_per_minute = general_per_minute
        self.generation_per_minute = generation_per_minute
        self._local_limiter = LocalWindowLimiter()
        self._script_sha: str | None = None
        self._was_degraded = False

    @staticmethod
    def _is_exempt(path: str) -> bool:
        return path in _EXEMPT_PATHS or path.startswith("/media/") or path == "/media"

    @staticmethod
    def _window() -> tuple[int, int]:
        now = time.time()
        whole_seconds = int(now)
        return int(now // 60), max(1, 60 - (whole_seconds % 60))

    def resolve_identity(self, request: Request) -> str:
        """Resolve a verified access-token subject or a trusted client address."""
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token:
            try:
                payload = decode_token(token)
            except (JWTError, ValueError, TypeError):
                payload = None
            if payload and not payload.get("refresh") and payload.get("sub"):
                return f"user:{payload['sub']}"

        if settings.TRUST_PROXY_HEADERS:
            forwarded_for = request.headers.get("X-Forwarded-For")
            if forwarded_for:
                return f"ip:{forwarded_for.split(',', 1)[0].strip()}"

        address = request.client.host if request.client else "unknown"
        return f"ip:{address}"

    async def increment_redis(self, redis: Any, key: str, limit: int, ttl: int) -> int:
        """Atomically increment a shared bucket and recover once from NOSCRIPT."""
        if self._script_sha is None:
            self._script_sha = await redis.script_load(RATE_LIMIT_LUA)

        try:
            return int(await redis.evalsha(self._script_sha, 1, key, limit, ttl))
        except NoScriptError:
            self._script_sha = await redis.script_load(RATE_LIMIT_LUA)
            return int(await redis.evalsha(self._script_sha, 1, key, limit, ttl))

    def increment_local(self, key: str, limit: int, window_epoch: int) -> int:
        return self._local_limiter.check_and_increment(key, limit, window_epoch)

    def _rate_limited_response(self, *, ttl: int, shared: bool) -> JSONResponse:
        headers = {}
        if shared:
            headers = {
                "X-RateLimit-Limit": str(self.general_per_minute),
                "X-RateLimit-Remaining": "0",
                "Retry-After": str(ttl),
            }
        return JSONResponse(
            status_code=429,
            content={"detail": _RATE_LIMITED_DETAIL},
            headers=headers,
        )

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        if self._is_exempt(path):
            return await call_next(request)

        identity = self.resolve_identity(request)
        window_epoch, ttl = self._window()
        general_key = f"ratelimit:v1:general:{identity}:{window_epoch}"
        generation_key = f"ratelimit:v1:generation:{identity}:{window_epoch}"
        is_generation = request.method == "POST" and path == "/api/v1/generations"

        degraded = (
            is_degraded(request) or getattr(request.app.state, "redis", None) is None
        )
        if degraded:
            self._was_degraded = True
            general_count = self.increment_local(
                general_key, self.general_per_minute, window_epoch
            )
            if general_count > self.general_per_minute:
                return self._rate_limited_response(ttl=ttl, shared=False)
            if is_generation:
                generation_count = self.increment_local(
                    generation_key, self.generation_per_minute, window_epoch
                )
                if generation_count > self.generation_per_minute:
                    return self._rate_limited_response(ttl=ttl, shared=False)
            return await call_next(request)

        if self._was_degraded:
            self._local_limiter.clear()
            self._was_degraded = False

        redis = request.app.state.redis
        try:
            general_count = await self.increment_redis(
                redis, general_key, self.general_per_minute, ttl
            )
            if general_count > self.general_per_minute:
                return self._rate_limited_response(ttl=ttl, shared=True)

            if is_generation:
                generation_count = await self.increment_redis(
                    redis, generation_key, self.generation_per_minute, ttl
                )
                if generation_count > self.generation_per_minute:
                    return self._rate_limited_response(ttl=ttl, shared=True)
        except Exception:
            enter_degraded(request.app, reason="rate limit Redis operation failed")
            self._was_degraded = True
            general_count = self.increment_local(
                general_key, self.general_per_minute, window_epoch
            )
            if general_count > self.general_per_minute:
                return self._rate_limited_response(ttl=ttl, shared=False)
            if is_generation:
                generation_count = self.increment_local(
                    generation_key, self.generation_per_minute, window_epoch
                )
                if generation_count > self.generation_per_minute:
                    return self._rate_limited_response(ttl=ttl, shared=False)
            return await call_next(request)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.general_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, self.general_per_minute - general_count)
        )
        return response
