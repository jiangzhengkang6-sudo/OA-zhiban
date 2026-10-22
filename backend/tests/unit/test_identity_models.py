"""Identity metadata must be registered and enforce stable relational ownership."""
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from app.db.base import Base
from app import models


def test_identity_tables_registered():
    names = {
        'oa_user', 'oa_department', 'oa_position', 'oa_membership', 'oa_role',
        'oa_permission', 'oa_user_role', 'oa_role_permission', 'oa_auth_session', 'oa_auth_throttle',
    }
    assert names <= set(Base.metadata.tables)
    assert models.OAUser.__table__.c.id.type.length == 64


def test_identity_constraints_and_refresh_history():
    user = Base.metadata.tables['oa_user']
    assert any(isinstance(c, UniqueConstraint) and {'tenant_id', 'normalized_username'} == set(c.columns.keys()) for c in user.constraints)
    member = Base.metadata.tables['oa_membership']
    assert sum(isinstance(c, ForeignKeyConstraint) for c in member.constraints) >= 2
    assert any(isinstance(c, CheckConstraint) for c in user.constraints)
    assert {'refresh_digest', 'family_id', 'consumed_at', 'revoked_at', 'absolute_expires_at'} <= set(Base.metadata.tables['oa_auth_session'].c.keys())
