from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from keystroke_dynamics.config import settings
from keystroke_dynamics.scores.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Unlike migrations/env.py (the account system's own, separate
# database, which always has a real database_url), scores_database_url
# is Optional -- None in every environment that hasn't opted into
# score collection at all, tests included. Only override the ini/CLI-
# provided URL when the app actually has one configured (a real
# deploy's `alembic -c alembic_scores.ini upgrade head`, reading
# SCORES_DATABASE_URL from its own environment); otherwise leave
# whatever was already set alone, so tests can point this at a
# dedicated test database via set_main_option("sqlalchemy.url", ...)
# before running upgrades, without needing SCORES_DATABASE_URL set in
# the whole test process's environment (which would also change what
# every other test sees settings.scores_database_url as).
if settings.scores_database_url:
    config.set_main_option("sqlalchemy.url", settings.scores_database_url)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
