"""Add municipality registry table for super-admin controls

Revision ID: add_muni_registry_20260411
Revises: add_program_prefs_20260411
Create Date: 2026-04-11 18:20:00.000000

"""

from datetime import datetime

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_muni_registry_20260411'
down_revision = 'add_program_prefs_20260411'
branch_labels = None
depends_on = None


_DEFAULT_MUNICIPALITIES = [
    'Santa Maria',
    'Siniloan',
    'Famy',
    'Pakil',
    'Pangil',
    'Mabitac',
    'Kalayaan',
    'Paete',
]


def _table_exists(inspector, table_name):
    return table_name in inspector.get_table_names()


def _index_names(inspector, table_name):
    return {index['name'] for index in inspector.get_indexes(table_name)}


def _collect_existing_profile_municipalities(bind, inspector):
    names = set(_DEFAULT_MUNICIPALITIES)

    for table_name in ('admin_users', 'community_users'):
        if not _table_exists(inspector, table_name):
            continue

        rows = bind.execute(
            sa.text(
                f"""
                SELECT DISTINCT municipality
                FROM {table_name}
                WHERE municipality IS NOT NULL
                  AND TRIM(municipality) <> ''
                """
            )
        ).fetchall()

        for row in rows:
            value = (row[0] or '').strip()
            if value:
                names.add(value)

    return sorted(names, key=lambda item: item.lower())


def _insert_missing_municipalities(bind, municipalities):
    existing_rows = bind.execute(
        sa.text(
            """
            SELECT name
            FROM municipalities
            WHERE name IS NOT NULL
            """
        )
    ).fetchall()

    existing = {(row[0] or '').strip().lower() for row in existing_rows if row[0]}
    now = datetime.utcnow()

    rows_to_insert = [
        {
            'name': municipality,
            'created_at': now,
            'updated_at': now,
        }
        for municipality in municipalities
        if municipality.strip().lower() not in existing
    ]

    if rows_to_insert:
        municipalities_table = sa.table(
            'municipalities',
            sa.column('name', sa.String(length=100)),
            sa.column('created_at', sa.DateTime()),
            sa.column('updated_at', sa.DateTime()),
        )
        op.bulk_insert(municipalities_table, rows_to_insert)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, 'municipalities'):
        op.create_table(
            'municipalities',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )

    inspector = sa.inspect(bind)
    if _table_exists(inspector, 'municipalities'):
        existing_indexes = _index_names(inspector, 'municipalities')
        if 'ix_municipalities_name' not in existing_indexes:
            op.create_index('ix_municipalities_name', 'municipalities', ['name'], unique=True)

        seed_names = _collect_existing_profile_municipalities(bind, inspector)
        _insert_missing_municipalities(bind, seed_names)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, 'municipalities'):
        if 'ix_municipalities_name' in _index_names(inspector, 'municipalities'):
            op.drop_index('ix_municipalities_name', table_name='municipalities')
        op.drop_table('municipalities')
