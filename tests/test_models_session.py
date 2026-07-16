"""Database-backed model and Alembic contracts for PR2 session controls."""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database.database import Base
from app.models.refresh_token import RefreshToken
from app.models.session import Session
from app.models.user import User


def test_session_and_refresh_token_defaults_are_applied_when_persisted():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine)()
    user = User(email="defaults@example.com", is_active=True)
    database.add(user)
    database.flush()

    session = Session(
        user_id=user.id, expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc)
    )
    database.add(session)
    database.flush()
    refresh = RefreshToken(
        token_hash="a" * 64,
        user_id=user.id,
        session_id=session.sid,
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    database.add(refresh)
    database.commit()

    assert session.sid is not None
    assert session.revoked is False
    assert refresh.id is not None
    assert refresh.revoked is False
    assert user.is_admin is False


def test_refresh_token_hash_is_unique_and_existing_users_keep_default_admin_flag():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine)()
    user = User(email="existing@example.com", is_active=True)
    database.add(user)
    database.flush()
    session = Session(
        user_id=user.id, expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc)
    )
    database.add(session)
    database.flush()
    first = RefreshToken(
        token_hash="b" * 64,
        user_id=user.id,
        session_id=session.sid,
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    duplicate = RefreshToken(
        token_hash="b" * 64,
        user_id=user.id,
        session_id=session.sid,
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    database.add(first)
    database.commit()
    database.add(duplicate)

    with pytest.raises(IntegrityError):
        database.commit()

    database.rollback()
    preserved_user = database.query(User).filter_by(email="existing@example.com").one()
    assert preserved_user.is_admin is False


class _AlembicRecorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return record


def _migration_module():
    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "002_pr2_session_controls.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pr2_session_controls_migration", path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_alembic_upgrade_and_downgrade_manage_session_control_schema(monkeypatch):
    migration = _migration_module()
    recorder = _AlembicRecorder()
    monkeypatch.setattr(migration, "op", recorder)

    migration.upgrade()
    upgrade_operations = [name for name, _args, _kwargs in recorder.calls]
    created_tables = [
        args[0] for name, args, _kwargs in recorder.calls if name == "create_table"
    ]
    added_columns = [
        args[:2] for name, args, _kwargs in recorder.calls if name == "add_column"
    ]

    assert created_tables == ["sessions", "refresh_tokens"]
    assert ("users",) in [column[:1] for column in added_columns]
    assert "create_foreign_key" in upgrade_operations
    assert "create_index" in upgrade_operations

    recorder.calls.clear()
    migration.downgrade()
    assert recorder.calls == [
        ("drop_table", ("refresh_tokens",), {}),
        ("drop_table", ("sessions",), {}),
        ("drop_column", ("users", "is_admin"), {}),
    ]
