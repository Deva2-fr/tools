"""Documents : dossiers (et sous-dossiers) ; guides interactifs lancés seulement à la 1re session."""
from alembic import op
import sqlalchemy as sa
import app.core.db


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('document_folders',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('parent_id', sa.Integer(), nullable=True),
    sa.Column('created_by', sa.String(length=255), nullable=False),
    sa.Column('created_at', app.core.db.UTCDateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['parent_id'], ['document_folders.id'], name='fk_document_folders_parent_id', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('document_folders', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_document_folders_parent_id'), ['parent_id'], unique=False)

    with op.batch_alter_table('file_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('folder_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_file_records_folder_id'), ['folder_id'], unique=False)
        batch_op.create_foreign_key('fk_file_records_folder_id', 'document_folders', ['folder_id'], ['id'], ondelete='SET NULL')

    # Les comptes existants ont déjà eu leur première connexion : plus de guide automatique.
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tours_done', sa.Boolean(), nullable=False, server_default=sa.true()))
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('tours_done', server_default=None)


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('tours_done')

    with op.batch_alter_table('file_records', schema=None) as batch_op:
        batch_op.drop_constraint('fk_file_records_folder_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_file_records_folder_id'))
        batch_op.drop_column('folder_id')

    with op.batch_alter_table('document_folders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_document_folders_parent_id'))

    op.drop_table('document_folders')
