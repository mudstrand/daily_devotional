from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool
import os
import models

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

DB_TARGET = os.getenv('DB_TARGET', 'bible').lower()

if DB_TARGET == 'bible':
    url = os.getenv('BIBLE_VERSE_DATABASE_URL')
    include_schemas = {'bible'}
elif DB_TARGET == 'devotional':
    url = os.getenv('DEVOTIONAL_DATABASE_URL')
    include_schemas = {'devotional'}
else:
    raise RuntimeError("DB_TARGET must be 'bible' or 'devotional'")

if not url:
    raise RuntimeError(f"Database URL env var missing for target '{DB_TARGET}'")

target_metadata = models.metadata


def include_object(object, name, type_, reflected, compare_to):
    obj_schema = getattr(object, 'schema', None)
    if obj_schema and obj_schema in include_schemas:
        return True
    if type_ == 'table' and name == 'alembic_version':
        return True
    return False


def run_migrations_offline():
    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_object=include_object,
        include_schemas=True,
        version_table_schema=list(include_schemas)[0],
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
        dialect_opts={'paramstyle': 'named'},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        {'sqlalchemy.url': url},
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
        future=True,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            include_schemas=True,
            version_table_schema=list(include_schemas)[0],
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()
