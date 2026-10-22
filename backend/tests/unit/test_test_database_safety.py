"""Destructive fixture guards must reject unsafe targets before connecting."""
import pytest

from app.db.safety import validate_test_targets


def targets(database="oa_agent_test"):
    return (
        f"postgresql+asyncpg://oa:oa@localhost:5433/{database}",
        f"postgresql+psycopg://oa:oa@localhost:5433/{database}",
        f"postgresql://oa:oa@localhost:5433/{database}",
    )


def test_accepts_explicit_test_targets():
    validate_test_targets("test", True, *targets())


@pytest.mark.parametrize("environment,allowed", [("development", True), ("production", True), ("test", False)])
def test_rejects_environment_or_missing_reset_permission(environment, allowed):
    with pytest.raises(RuntimeError):
        validate_test_targets(environment, allowed, *targets())


@pytest.mark.parametrize("database", ["oa_agent", "postgres", "oa_agent_test_extra", "", "test"])
def test_rejects_non_test_database(database):
    with pytest.raises(RuntimeError):
        validate_test_targets("test", True, *targets(database))


def test_rejects_checkpointer_pointing_to_development():
    async_url, sync_url, _ = targets()
    with pytest.raises(RuntimeError):
        validate_test_targets("test", True, async_url, sync_url, targets("oa_agent")[2])


def test_rejects_different_hosts_or_databases():
    async_url, sync_url, checkpoint = targets()
    with pytest.raises(RuntimeError):
        validate_test_targets("test", True, async_url, sync_url, checkpoint.replace("localhost", "other-host"))


def test_error_does_not_leak_database_credentials():
    with pytest.raises(RuntimeError) as error:
        validate_test_targets("test", True, "postgresql://user:secret@host/oa_agent", *targets()[1:])
    assert "secret" not in str(error.value)
