"""Run private migrations on the caller's locked SQLite connection."""

from alembic import context

connection = context.config.attributes["connection"]
context.configure(connection=connection, transaction_per_migration=False)
with context.begin_transaction():
    context.run_migrations()
