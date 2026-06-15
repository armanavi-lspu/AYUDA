"""Seed municipality admin accounts and clone existing programs.

Revision ID: seed_muni_admins_20260411
Revises: add_muni_registry_20260411
Create Date: 2026-04-11 21:00:00.000000

"""

from datetime import datetime

from alembic import op
import sqlalchemy as sa
from werkzeug.security import generate_password_hash


# revision identifiers, used by Alembic.
revision = 'seed_muni_admins_20260411'
down_revision = 'add_muni_registry_20260411'
branch_labels = None
depends_on = None


_ADMIN_ACCOUNTS = [
    {
        'municipality': 'Santa Maria',
        'email': 'MSWDOStaMaria@email.com',
        'password': 'StaMariaMSWD_2026',
    },
    {
        'municipality': 'Siniloan',
        'email': 'MSWDOSiniloan@email.com',
        'password': 'SiniloanMSWD_2026',
    },
    {
        'municipality': 'Pangil',
        'email': 'MSWDOPangil@email.com',
        'password': 'PangilMSWD_2026',
    },
    {
        'municipality': 'Pakil',
        'email': 'MSWDOPakil@email.com',
        'password': 'PakilMSWD_2026',
    },
    {
        'municipality': 'Famy',
        'email': 'MSWDOFamy@email.com',
        'password': 'FamyMSWD_2026',
    },
    {
        'municipality': 'Kalayaan',
        'email': 'MSWDOKalayaan@email.com',
        'password': 'KalayaanMSWD_2026',
    },
    {
        'municipality': 'Paete',
        'email': 'MSWDOPaete@email.com',
        'password': 'PaeteMSWD_2026',
    },
]


def _table_exists(inspector, table_name):
    return table_name in inspector.get_table_names()


def _upsert_admin_user(bind, users_table, admin_users_table, account):
    now = datetime.utcnow()
    email = account['email'].strip().lower()
    municipality = account['municipality'].strip()
    password_hash = generate_password_hash(account['password'], method='pbkdf2:sha256')

    existing_user = bind.execute(
        sa.select(users_table.c.id)
        .where(sa.func.lower(users_table.c.email) == email)
        .limit(1)
    ).mappings().first()

    if existing_user:
        user_id = existing_user['id']
        bind.execute(
            sa.update(users_table)
            .where(users_table.c.id == user_id)
            .values(
                password_hash=password_hash,
                first_name='MSWDO',
                middle_name=None,
                last_name=municipality,
                role='admin',
            )
        )
    else:
        result = bind.execute(
            sa.insert(users_table).values(
                email=email,
                password_hash=password_hash,
                first_name='MSWDO',
                middle_name=None,
                last_name=municipality,
                role='admin',
                created_at=now,
            )
        )
        user_id = result.inserted_primary_key[0]

    existing_admin_profile = bind.execute(
        sa.select(admin_users_table.c.id)
        .where(admin_users_table.c.user_id == user_id)
        .limit(1)
    ).scalar()

    if existing_admin_profile is None:
        bind.execute(
            sa.insert(admin_users_table).values(
                user_id=user_id,
                municipality=municipality,
                created_at=now,
            )
        )
    else:
        bind.execute(
            sa.update(admin_users_table)
            .where(admin_users_table.c.user_id == user_id)
            .values(municipality=municipality)
        )

    return user_id


def _clone_programs_for_admin(
    bind,
    admin_user_id,
    programs_table,
    source_program_rows,
    program_requirements_table,
    requirements_by_program,
    workflow_steps_table,
    steps_by_program,
):
    if 'user_id' not in programs_table.c:
        return

    existing_program_count = bind.execute(
        sa.select(sa.func.count())
        .select_from(programs_table)
        .where(programs_table.c.user_id == admin_user_id)
    ).scalar() or 0

    if existing_program_count > 0:
        return

    program_copy_columns = [col.name for col in programs_table.columns if col.name != 'id']
    requirement_copy_columns = []
    step_copy_columns = []

    if program_requirements_table is not None:
        requirement_copy_columns = [
            col.name for col in program_requirements_table.columns if col.name != 'id'
        ]

    if workflow_steps_table is not None:
        step_copy_columns = [col.name for col in workflow_steps_table.columns if col.name != 'id']

    for source_program in source_program_rows:
        new_program_values = {
            col_name: source_program[col_name]
            for col_name in program_copy_columns
            if col_name != 'user_id'
        }
        new_program_values['user_id'] = admin_user_id

        insert_result = bind.execute(sa.insert(programs_table).values(**new_program_values))
        new_program_id = insert_result.inserted_primary_key[0]

        if program_requirements_table is not None:
            for source_requirement in requirements_by_program.get(source_program['id'], []):
                new_requirement_values = {
                    col_name: source_requirement[col_name]
                    for col_name in requirement_copy_columns
                    if col_name != 'program_id'
                }
                new_requirement_values['program_id'] = new_program_id
                bind.execute(sa.insert(program_requirements_table).values(**new_requirement_values))

        if workflow_steps_table is not None:
            for source_step in steps_by_program.get(source_program['id'], []):
                new_step_values = {
                    col_name: source_step[col_name]
                    for col_name in step_copy_columns
                    if col_name != 'program_id'
                }
                new_step_values['program_id'] = new_program_id
                bind.execute(sa.insert(workflow_steps_table).values(**new_step_values))


def _group_rows_by_program(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row['program_id'], []).append(row)
    return grouped


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, 'users') or not _table_exists(inspector, 'admin_users'):
        return

    metadata = sa.MetaData()
    users_table = sa.Table('users', metadata, autoload_with=bind)
    admin_users_table = sa.Table('admin_users', metadata, autoload_with=bind)

    programs_table = None
    source_program_rows = []
    requirements_by_program = {}
    steps_by_program = {}
    program_requirements_table = None
    workflow_steps_table = None

    if _table_exists(inspector, 'programs'):
        programs_table = sa.Table('programs', metadata, autoload_with=bind)
        source_program_rows = [
            dict(row)
            for row in bind.execute(
                sa.select(programs_table).order_by(programs_table.c.id)
            ).mappings().all()
        ]

    source_program_ids = [row['id'] for row in source_program_rows]

    if source_program_ids and _table_exists(inspector, 'program_requirements'):
        program_requirements_table = sa.Table('program_requirements', metadata, autoload_with=bind)
        requirement_rows = [
            dict(row)
            for row in bind.execute(
                sa.select(program_requirements_table).where(
                    program_requirements_table.c.program_id.in_(source_program_ids)
                )
            ).mappings().all()
        ]
        requirements_by_program = _group_rows_by_program(requirement_rows)

    if source_program_ids and _table_exists(inspector, 'program_workflow_steps'):
        workflow_steps_table = sa.Table('program_workflow_steps', metadata, autoload_with=bind)
        workflow_rows = [
            dict(row)
            for row in bind.execute(
                sa.select(workflow_steps_table)
                .where(workflow_steps_table.c.program_id.in_(source_program_ids))
                .order_by(workflow_steps_table.c.program_id, workflow_steps_table.c.step_order)
            ).mappings().all()
        ]
        steps_by_program = _group_rows_by_program(workflow_rows)

    for account in _ADMIN_ACCOUNTS:
        admin_user_id = _upsert_admin_user(bind, users_table, admin_users_table, account)

        if programs_table is not None and source_program_rows:
            _clone_programs_for_admin(
                bind,
                admin_user_id,
                programs_table,
                source_program_rows,
                program_requirements_table,
                requirements_by_program,
                workflow_steps_table,
                steps_by_program,
            )


def downgrade():
    # Intentionally left as a no-op because this migration seeds live user accounts
    # and cloned program data that may already be referenced by production records.
    pass