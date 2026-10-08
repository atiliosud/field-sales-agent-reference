from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from context_service.db import migrate
from context_service.models import Base


def test_migration_creates_the_four_tables_and_matches_the_models(tmp_path):
    path = tmp_path / "migrated.db"

    migrate(f"sqlite+aiosqlite:///{path}")

    engine = create_engine(f"sqlite:///{path}")
    assert {"conversations", "turns", "facts", "artifacts"} <= set(
        inspect(engine).get_table_names()
    )
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_migrating_twice_is_harmless(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'twice.db'}"

    migrate(url)
    migrate(url)
