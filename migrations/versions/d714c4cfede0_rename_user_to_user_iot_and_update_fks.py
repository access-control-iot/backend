"""Rename User to User_iot, migrate data, replace huella -> huella_id, and update FKs.

Revision ID: d714c4cfede0
Revises: e452eeafdaa4
Create Date: 2025-11-20 18:01:20.454146
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

# revision identifiers
revision = 'd714c4cfede0'
down_revision = 'e452eeafdaa4'
branch_labels = None
depends_on = None


def upgrade():

    # 1️⃣ Crear nueva tabla user_iot SOLO si no existe
    bind = op.get_bind()
    inspector = inspect(bind)

    if "user_iot" not in inspector.get_table_names():

        op.create_table(
            'user_iot',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('username', sa.String(80), nullable=False),
            sa.Column('password_hash', sa.Text(), nullable=False),
            sa.Column('role_id', sa.Integer(), sa.ForeignKey("role.id")),
            sa.Column('nombre', sa.String(80), nullable=False),
            sa.Column('apellido', sa.String(80), nullable=False),
            sa.Column('genero', sa.String(10)),
            sa.Column('fecha_nacimiento', sa.Date()),
            sa.Column('fecha_contrato', sa.Date()),
            sa.Column('area_trabajo', sa.String(80)),
            sa.Column('huella_id', sa.Integer()),
            sa.Column('rfid', sa.String(64)),
            sa.Column('created_at', sa.DateTime()),
            sa.Column('updated_at', sa.DateTime()),
        )

        with op.batch_alter_table('user_iot') as batch:
            batch.create_index('ix_user_iot_area_trabajo', ['area_trabajo'])
            batch.create_index('ix_user_iot_rfid', ['rfid'], unique=True)
            batch.create_index('ix_user_iot_username', ['username'], unique=True)

        # Copiar datos desde user → user_iot SOLO si user existe
        if "user" in inspector.get_table_names():
            op.execute("""
                INSERT INTO user_iot (
                    id, username, password_hash, role_id, nombre, apellido, genero,
                    fecha_nacimiento, fecha_contrato, area_trabajo, huella_id,
                    rfid, created_at, updated_at
                )
                SELECT
                    id, username, password_hash, role_id, nombre, apellido, genero,
                    fecha_nacimiento, fecha_contrato, area_trabajo,
                    NULL AS huella_id,
                    rfid, created_at, updated_at
                FROM "user";
            """)

            # Eliminar tabla antigua
            with op.batch_alter_table('user') as batch:
                batch.drop_index('ix_user_area_trabajo')
                batch.drop_index('ix_user_rfid')
                batch.drop_index('ix_user_username')

            op.drop_table('user')

    # 6️⃣ Actualizar FKs (esto siempre corre)
    tables_with_user_fk = [
        ("access_log", "access_log_user_id_fkey"),
        ("attendance", "attendance_user_id_fkey"),
        ("failed_attempt", "failed_attempt_user_id_fkey"),
        ("user_schedule", "user_schedule_user_id_fkey"),
    ]

    for table, fk_name in tables_with_user_fk:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(fk_name, type_='foreignkey')
            batch.create_foreign_key(None, 'user_iot', ['user_id'], ['id'])

    with op.batch_alter_table('schedule_audit') as batch:
        batch.drop_constraint('schedule_audit_admin_id_fkey', type_='foreignkey')
        batch.drop_constraint('schedule_audit_user_id_fkey', type_='foreignkey')
        batch.create_foreign_key(None, 'user_iot', ['admin_id'], ['id'])
        batch.create_foreign_key(None, 'user_iot', ['user_id'], ['id'])
def downgrade():

    # 1️⃣ Restaurar tabla original user
    op.create_table(
        'user',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('username', sa.String(80), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('role_id', sa.Integer(), sa.ForeignKey("role.id")),
        sa.Column('nombre', sa.String(80), nullable=False),
        sa.Column('apellido', sa.String(80), nullable=False),
        sa.Column('genero', sa.String(10)),
        sa.Column('fecha_nacimiento', sa.Date()),
        sa.Column('fecha_contrato', sa.Date()),
        sa.Column('area_trabajo', sa.String(80)),
        sa.Column('huella', postgresql.BYTEA()),  # campo antiguo
        sa.Column('rfid', sa.String(64)),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
    )

    # 2️⃣ Copiar datos de vuelta (huella queda NULL)
    op.execute("""
        INSERT INTO "user" (
            id, username, password_hash, role_id, nombre, apellido, genero,
            fecha_nacimiento, fecha_contrato, area_trabajo, huella,
            rfid, created_at, updated_at
        )
        SELECT
            id, username, password_hash, role_id, nombre, apellido, genero,
            fecha_nacimiento, fecha_contrato, area_trabajo,
            NULL AS huella,
            rfid, created_at, updated_at
        FROM user_iot;
    """)

    # 3️⃣ Restaurar índices
    with op.batch_alter_table('user') as batch:
        batch.create_index('ix_user_username', ['username'], unique=True)
        batch.create_index('ix_user_rfid', ['rfid'], unique=True)
        batch.create_index('ix_user_area_trabajo', ['area_trabajo'])

    # 4️⃣ Restaurar FKs
    tables_with_user_fk = [
        ("access_log", None, "access_log_user_id_fkey"),
        ("attendance", None, "attendance_user_id_fkey"),
        ("failed_attempt", None, "failed_attempt_user_id_fkey"),
        ("user_schedule", None, "user_schedule_user_id_fkey"),
    ]

    for table, _, fk_name in tables_with_user_fk:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(None, type_='foreignkey')
            batch.create_foreign_key(fk_name, 'user', ['user_id'], ['id'])

    # schedule_audit
    with op.batch_alter_table('schedule_audit') as batch:
        batch.drop_constraint(None, type_='foreignkey')
        batch.drop_constraint(None, type_='foreignkey')
        batch.create_foreign_key('schedule_audit_user_id_fkey', 'user', ['user_id'], ['id'])
        batch.create_foreign_key('schedule_audit_admin_id_fkey', 'user', ['admin_id'], ['id'])

    # 5️⃣ Eliminar tabla user_iot
    with op.batch_alter_table('user_iot') as batch:
        batch.drop_index('ix_user_iot_username')
        batch.drop_index('ix_user_iot_rfid')
        batch.drop_index('ix_user_iot_area_trabajo')

    op.drop_table('user_iot')
