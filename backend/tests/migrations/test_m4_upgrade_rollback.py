"""Forward-only migration and explicitly declared application compatibility."""
import pytest
from alembic import command
from sqlalchemy import create_engine, text

from app.db import migrations


@pytest.mark.parametrize('revision,heads', [
    ('unknown', {'0029'}), ('8cb8fc625d3bb1c175f17cb0321e32837171a6b2', {'0030'}),
    ('8cb8fc625d3bb1c175f17cb0321e32837171a6b2', set()),
    ('8cb8fc625d3bb1c175f17cb0321e32837171a6b2', {'0029', 'other'}),
])
def test_incompatible_application_is_refused(revision, heads):
    with pytest.raises(RuntimeError):
        migrations.assert_application_rollback_compatible(revision, heads)


def test_declared_baseline_is_compatible():
    migrations.assert_application_rollback_compatible('8cb8fc625d3bb1c175f17cb0321e32837171a6b2', {'0029'})


def test_repeat_upgrade_preserves_business_rows(safe_database):
    engine = create_engine(safe_database.database_sync_url)
    try:
        with engine.begin() as connection:
            config = migrations.migration_config()
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
            before = connection.execute(text('SELECT id, state, revision FROM oa_leave ORDER BY id')).all()
            assert before, 'Run after restored business drill; empty data is not compatibility evidence'
            command.upgrade(config, 'head')
            migrations.assert_schema_current(connection)
            assert connection.execute(text('SELECT id, state, revision FROM oa_leave ORDER BY id')).all() == before
    finally:
        engine.dispose()
