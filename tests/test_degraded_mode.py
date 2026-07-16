"""Redis-degraded lifecycle and recovery contracts."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.middleware import degraded


def test_degraded_transition_logs_warning_and_uses_short_access_ttl(caplog):
    app = SimpleNamespace(state=SimpleNamespace(degraded=False, redis=object()))
    request = SimpleNamespace(app=app)

    with caplog.at_level(logging.WARNING, logger="app.middleware.degraded"):
        degraded.enter_degraded(app, reason="redis ping failed")

    assert app.state.degraded is True
    assert app.state.redis is None
    assert degraded.access_token_ttl(request).total_seconds() == 120
    assert "entering degraded mode" in caplog.text


def test_recovery_stays_degraded_on_warmup_failure_then_logs_success(
    monkeypatch, caplog
):
    app = SimpleNamespace(state=SimpleNamespace(degraded=True, redis=None))
    redis = SimpleNamespace(ping=AsyncMock(return_value=True))

    monkeypatch.setattr(
        degraded,
        "repopulate_blacklist_cache",
        AsyncMock(side_effect=OSError("db down")),
    )
    assert asyncio.run(degraded.recover_redis(app, redis)) is False
    assert app.state.degraded is True

    monkeypatch.setattr(degraded, "repopulate_blacklist_cache", AsyncMock())
    with caplog.at_level(logging.INFO, logger="app.middleware.degraded"):
        assert asyncio.run(degraded.recover_redis(app, redis)) is True

    assert app.state.degraded is False
    assert app.state.redis is redis
    assert "blacklist projection repopulated" in caplog.text


class _TaskSpy:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def __await__(self):
        async def done():
            return None

        return done().__await__()


def test_lifespan_cancels_background_recovery_and_cleanup_tasks(monkeypatch):
    import app.main as main

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Engine:
        def connect(self):
            return Connection()

    class DatabaseSession:
        def close(self):
            return None

    async def redis_client(*_args, **_kwargs):
        return SimpleNamespace()

    tasks = []

    def create_task(coroutine):
        coroutine.close()
        task = _TaskSpy()
        tasks.append(task)
        return task

    monkeypatch.setattr(main, "engine", Engine())
    monkeypatch.setattr(main, "SessionLocal", DatabaseSession)
    monkeypatch.setattr(main, "seed_styles", lambda _db: None)
    monkeypatch.setattr(main, "create_redis_pool", redis_client)
    monkeypatch.setattr(main, "set_redis", lambda _client: None)
    monkeypatch.setattr(main, "cleanup_scheduler", AsyncMock())
    monkeypatch.setattr(main.asyncio, "create_task", create_task)
    monkeypatch.setattr(main, "close_redis", AsyncMock())

    async def exercise_lifespan():
        async with main.lifespan(main.app):
            assert main.app.state.degraded is False

    asyncio.run(exercise_lifespan())

    assert len(tasks) == 2
    assert all(task.cancelled for task in tasks)
    main.close_redis.assert_awaited_once()
