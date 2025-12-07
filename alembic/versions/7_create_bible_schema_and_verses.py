import sqlalchemy as sa
from alembic import op

revision = "7_create_bible_schema_and_verses"
down_revision = None  # or set to your latest revision id
branch_labels = None
depends_on = None


def upgrade():
    # Ensure schema exists
    op.execute("CREATE SCHEMA IF NOT EXISTS bible AUTHORIZATION bible")

    # Create table in the bible schema
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
        schema="bible",
    )


def downgrade():
    op.drop_table("verses", schema="bible")
    # Optional: drop schema if empty
    # op.execute("DROP SCHEMA IF EXISTS bible CASCADE")
