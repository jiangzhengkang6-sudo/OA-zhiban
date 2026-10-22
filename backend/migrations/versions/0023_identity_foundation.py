"""Add local identity tables without rewriting historical business ownership."""
from alembic import op
import sqlalchemy as sa

revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def identity_columns():
    return [sa.Column('id', sa.String(64), primary_key=True), sa.Column('tenant_id', sa.String(64), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def fk(column, target):
    return sa.ForeignKeyConstraint(['tenant_id', column], [target + '.tenant_id', target + '.id'], name='fk_identity_' + column + '_' + target)


def upgrade():
    op.create_table('oa_user', *identity_columns(),
        sa.Column('normalized_username', sa.String(128), nullable=False), sa.Column('display_name', sa.String(128), nullable=False),
        sa.Column('password_hash', sa.String(512), nullable=False), sa.Column('status', sa.String(16), nullable=False),
        sa.Column('auth_version', sa.Integer(), nullable=False), sa.Column('authorization_version', sa.Integer(), nullable=False),
        sa.Column('failed_attempts', sa.Integer(), nullable=False), sa.Column('locked_until', sa.DateTime(timezone=True)),
        sa.Column('handoff_pending', sa.Boolean(), nullable=False), sa.UniqueConstraint('tenant_id', 'id', name='uq_oa_user_tenant_identity'),
        sa.UniqueConstraint('tenant_id', 'normalized_username', name='uq_oa_user_tenant_username'),
        sa.CheckConstraint("status IN ('active', 'disabled')", name='user_status'),
        sa.CheckConstraint('failed_attempts >= 0 AND auth_version >= 1 AND authorization_version >= 1', name='user_versions'))
    op.create_table('oa_department', *identity_columns(), sa.Column('name', sa.String(128), nullable=False),
        sa.Column('parent_id', sa.String(64)), sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_oa_department_tenant_identity'), sa.UniqueConstraint('tenant_id', 'name', name='uq_oa_department_tenant_name'), fk('parent_id', 'oa_department'),
        sa.CheckConstraint('parent_id IS NULL OR parent_id <> id', name='department_parent'))
    op.create_table('oa_position', *identity_columns(), sa.Column('name', sa.String(128), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False), sa.UniqueConstraint('tenant_id', 'id', name='uq_oa_position_tenant_identity'), sa.UniqueConstraint('tenant_id', 'name', name='uq_oa_position_tenant_name'))
    op.create_table('oa_membership', sa.Column('tenant_id', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(64), primary_key=True), sa.Column('department_id', sa.String(64), nullable=False),
        sa.Column('position_id', sa.String(64)), sa.Column('manager_id', sa.String(64)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        fk('user_id', 'oa_user'), fk('department_id', 'oa_department'), fk('position_id', 'oa_position'), fk('manager_id', 'oa_user'),
        sa.CheckConstraint('manager_id IS NULL OR manager_id <> user_id', name='membership_manager'))
    op.create_index('ix_oa_membership_department_id', 'oa_membership', ['department_id'])
    op.create_table('oa_role', *identity_columns(), sa.Column('code', sa.String(64), nullable=False),
        sa.Column('name', sa.String(128), nullable=False), sa.UniqueConstraint('tenant_id', 'id', name='uq_oa_role_tenant_identity'), sa.UniqueConstraint('tenant_id', 'code', name='uq_oa_role_tenant_code'))
    op.create_table('oa_permission', sa.Column('id', sa.String(64), primary_key=True), sa.Column('resource', sa.String(64), nullable=False),
        sa.Column('action', sa.String(64), nullable=False), sa.Column('scope', sa.String(16), nullable=False),
        sa.UniqueConstraint('resource', 'action', 'scope'), sa.CheckConstraint("scope IN ('self', 'department')", name='permission_scope'))
    op.create_table('oa_user_role', sa.Column('tenant_id', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(64), primary_key=True), sa.Column('role_id', sa.String(64), primary_key=True),
        fk('user_id', 'oa_user'), fk('role_id', 'oa_role'))
    op.create_table('oa_role_permission', sa.Column('tenant_id', sa.String(64), primary_key=True),
        sa.Column('role_id', sa.String(64), primary_key=True), sa.Column('permission_id', sa.String(64), primary_key=True),
        fk('role_id', 'oa_role'), sa.ForeignKeyConstraint(['permission_id'], ['oa_permission.id']))
    op.create_table('oa_auth_session', *identity_columns(), sa.Column('user_id', sa.String(64), nullable=False),
        sa.Column('family_id', sa.String(64), nullable=False), sa.Column('refresh_digest', sa.String(64), nullable=False),
        sa.Column('auth_version', sa.Integer(), nullable=False), sa.Column('absolute_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True)), sa.Column('revoked_at', sa.DateTime(timezone=True)),
        fk('user_id', 'oa_user'), sa.UniqueConstraint('refresh_digest'))
    op.create_index('ix_oa_auth_session_user_id', 'oa_auth_session', ['user_id'])
    op.create_index('ix_oa_auth_session_family_id', 'oa_auth_session', ['family_id'])
    op.create_table('oa_auth_throttle', sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('attempts', sa.Integer(), nullable=False), sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('attempts >= 0', name='throttle_attempts'))


def downgrade():
    for name in ('oa_auth_throttle', 'oa_auth_session', 'oa_role_permission', 'oa_user_role', 'oa_permission',
                 'oa_membership', 'oa_role', 'oa_position', 'oa_department', 'oa_user'):
        op.drop_table(name)
