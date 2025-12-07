from alembic import op
import sqlalchemy as sa

revision = "6_manual_create_verses"
down_revision = None  # run independently of earlier empty revisions
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "verses",
        sa.Column("book", sa.Text(), nullable=False),
        sa.Column("chapter", sa.Integer(), nullable=False),
        sa.Column("verse", sa.Integer(), nullable=False),
        sa.Column("translation", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint(
            "book", "chapter", "verse", "translation", name="pk_verses"
        ),
    )


def downgrade():
    op.drop_table("verses")
