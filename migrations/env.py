import logging
from logging.config import fileConfig

from flask import current_app
from alembic import context

from app import create_app, db
from app.models import *  # Importa todos los modelos

# Configuración de Alembic
config = context.config

# Configura logging
fileConfig(config.config_file_name)
logger = logging.getLogger('alembic.env')

# Asigna explícitamente los metadata de SQLAlchemy
target_metadata = db.metadata

# Si quieres, puedes ajustar la URL desde la app de Flask
config.set_main_option('sqlalchemy.url', str(current_app.extensions['migrate'].db.engine.url))

def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode."""
    connectable = current_app.extensions['migrate'].db.engine

    # Evitar migraciones vacías
    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, 'autogenerate', False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info('No changes in schema detected.')

    conf_args = current_app.extensions['migrate'].configure_args
    if conf_args.get("process_revision_directives") is None:
        conf_args["process_revision_directives"] = process_revision_directives

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            **conf_args
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
