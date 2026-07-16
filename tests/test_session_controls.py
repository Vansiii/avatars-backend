"""PR2a session-control contracts."""

import asyncio
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects.postgresql import UUID

from app.config.settings import Settings
from app.middleware import degraded
from app.models.refresh_token import RefreshToken
from app.models.session import Session
from app.models.user import User


def test_session_and_refresh_token_models_use_uuid_foreign_keys():
    assert isinstance(Session.__table__.c.sid.type, UUID)
    assert isinstance(Session.__table__.c.user_id.type, UUID)
    assert {fk.target_fullname for fk in Session.__table__.c.user_id.foreign_keys} == {
        "users.id"
    }
    assert isinstance(RefreshToken.__table__.c.id.type, UUID)
    assert isinstance(RefreshToken.__table__.c.user_id.type, UUID)
    assert isinstance(RefreshToken.__table__.c.session_id.type, UUID)
    assert {
        fk.target_fullname for fk in RefreshToken.__table__.c.session_id.foreign_keys
    } == {"sessions.sid"}
    assert RefreshToken.__table__.c.token_hash.unique is True
    assert User.__table__.c.is_admin.nullable is False


def test_session_and_refresh_token_defaults_are_safe():
    session = Session(
        user_id="550e8400-e29b-41d4-a716-446655440000",
        expires_at="2030-01-01T00:00:00Z",
    )
    token = RefreshToken(
        token_hash="a" * 64,
        user_id="550e8400-e29b-41d4-a716-446655440000",
        session_id="550e8400-e29b-41d4-a716-446655440000",
        expires_at="2030-01-01T00:00:00Z",
    )
    assert session.revoked is None
    assert token.revoked is None
    assert Session.__table__.c.revoked.server_default is not None
    assert RefreshToken.__table__.c.revoked.server_default is not None


def test_session_control_setting_defaults(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    settings = Settings()
    assert settings.RATE_LIMIT_GENERAL_PER_MINUTE == 100
    assert settings.RATE_LIMIT_GENERATION_PER_MINUTE == 20
    assert settings.TRUST_PROXY_HEADERS is False
    assert settings.DEGRADED_ACCESS_TOKEN_EXPIRE_MINUTES == 2


def test_enter_degraded_is_idempotent_and_access_ttl_is_shortened():
    app = SimpleNamespace(state=SimpleNamespace(degraded=False, redis=object()))
    request = SimpleNamespace(app=app)

    degraded.enter_degraded(app, reason="redis ping failed")
    assert app.state.degraded is True
    assert app.state.redis is None
    assert degraded.is_degraded(request) is True
    assert degraded.access_token_ttl(request) == timedelta(minutes=2)

    degraded.enter_degraded(app, reason="ignored second transition")
    assert app.state.degraded is True


def test_access_ttl_uses_normal_setting_when_healthy():
    app = SimpleNamespace(state=SimpleNamespace(degraded=False))
    request = SimpleNamespace(app=app)
    assert degraded.access_token_ttl(request) == timedelta(
        minutes=Settings().ACCESS_TOKEN_EXPIRE_MINUTES
    )


def test_repopulate_blacklist_cache_writes_only_unexpired_revoked_sessions(monkeypatch):
    expires_at = degraded.datetime.now(degraded.timezone.utc) + timedelta(minutes=5)
    revoked_session = SimpleNamespace(sid="sid-1", expires_at=expires_at)

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def scalars(self):
            return self

        def all(self):
            return self.rows

    class DatabaseSession:
        def __init__(self):
            self.calls = 0
            self.closed = False

        def execute(self, _statement):
            self.calls += 1
            return Result([revoked_session] if self.calls == 1 else [])

        def close(self):
            self.closed = True

    class Pipeline:
        def __init__(self):
            self.entries = []
            self.execute = AsyncMock()

        def set(self, key, value, *, ex):
            self.entries.append((key, value, ex))

    db = DatabaseSession()
    pipeline = Pipeline()
    redis_client = SimpleNamespace(pipeline=lambda **_kwargs: pipeline)
    monkeypatch.setattr(degraded, "SessionLocal", lambda: db)

    asyncio.run(degraded.repopulate_blacklist_cache(SimpleNamespace(), redis_client))

    assert pipeline.entries[0][:2] == ("blacklist:v1:sid:sid-1", "1")
    assert pipeline.entries[0][2] > 0
    pipeline.execute.assert_awaited_once()
    assert db.closed is True


def test_recover_redis_keeps_degraded_until_cache_repopulation_succeeds(monkeypatch):
    app = SimpleNamespace(state=SimpleNamespace(degraded=True, redis=None))
    redis_client = SimpleNamespace(ping=AsyncMock(return_value=True))

    async def fail_warmup(*_args):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(degraded, "repopulate_blacklist_cache", fail_warmup)
    assert asyncio.run(degraded.recover_redis(app, redis_client)) is False
    assert app.state.degraded is True
    assert app.state.redis is None

    monkeypatch.setattr(degraded, "repopulate_blacklist_cache", AsyncMock())
    assert asyncio.run(degraded.recover_redis(app, redis_client)) is True
    assert app.state.degraded is False
    assert app.state.redis is redis_client


def test_lifespan_starts_in_degraded_mode_when_redis_is_unavailable(monkeypatch):
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
            pass

    async def unavailable(*_args, **_kwargs):
        raise main.RedisUnavailable("unavailable")

    async def idle_cleanup(**_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(main, "engine", Engine())
    monkeypatch.setattr(main, "SessionLocal", DatabaseSession)
    monkeypatch.setattr(main, "seed_styles", lambda _db: None)
    monkeypatch.setattr(main, "create_redis_pool", unavailable)
    monkeypatch.setattr(main, "cleanup_scheduler", idle_cleanup)
    monkeypatch.setattr(main, "close_redis", AsyncMock())

    async def run_lifespan():
        async with main.lifespan(main.app):
            assert main.app.state.degraded is True
            assert main.app.state.redis is None

    asyncio.run(run_lifespan())


def test_session_controls_documentation_is_present():
    root = Path(__file__).resolve().parents[2]
    agentic = root / "avatars-agentic" / ".agents"
    assert "PostgreSQL" in (
        agentic / "skills" / "operations" / "ADR-session-controls.md"
    ).read_text(encoding="utf-8")
    assert "PR2" in (agentic / "steering" / "backlog.md").read_text(encoding="utf-8")
    assert (
        "session controls"
        in (agentic / "memory" / "HEARTBEAT.md").read_text(encoding="utf-8").lower()
    )
    assert "blacklist:v1:sid" in (agentic / "skills" / "backend.md").read_text(
        encoding="utf-8"
    )
