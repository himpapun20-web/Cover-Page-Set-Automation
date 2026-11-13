from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from .database import engine
from .models import Base

PRE_PASSWORD_REVISION = "f3819c2a4d10"


def _validate_unversioned_schema() -> bool:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    application_tables = set(Base.metadata.tables)
    if not application_tables.issubset(tables):
        missing = sorted(application_tables - tables)
        raise RuntimeError(f"Existing database schema is incomplete; missing tables: {', '.join(missing)}.")

    missing_columns: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name not in existing_columns and not (table_name == "users" and column.name == "password_hash"):
                missing_columns.append(f"{table_name}.{column.name}")
    if missing_columns:
        raise RuntimeError(f"Existing database schema is incomplete; missing columns: {', '.join(missing_columns)}.")

    direction_check = next(
        (constraint for constraint in inspector.get_check_constraints("inspections") if constraint.get("name") == "ck_inspections_direction"),
        None,
    )
    direction_sql = (direction_check or {}).get("sqltext", "").upper()
    if "UPSTREAM" not in direction_sql or "DOWNSTREAM" not in direction_sql:
        raise RuntimeError("Existing database schema has an outdated inspection-direction constraint.")

    for table_name, column_name in (("companies", "logo_asset_id"), ("users", "signature_asset_id")):
        has_asset_foreign_key = any(
            constraint.get("constrained_columns") == [column_name]
            and constraint.get("referred_table") == "assets"
            and constraint.get("referred_columns") == ["id"]
            for constraint in inspector.get_foreign_keys(table_name)
        )
        if not has_asset_foreign_key:
            raise RuntimeError(f"Existing database schema is missing the {table_name}.{column_name} asset relationship.")

    return "password_hash" in {column["name"] for column in inspector.get_columns("users")}


def main() -> None:
    config_path = Path(__file__).resolve().parents[1] / "alembic.ini"
    config = Config(str(config_path))
    config.set_main_option("script_location", str(config_path.parent / "alembic"))
    tables = set(inspect(engine).get_table_names())
    if not (tables - {"alembic_version"}):
        command.upgrade(config, "head")
        return

    if "alembic_version" in tables:
        with engine.connect() as connection:
            revisions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    else:
        revisions = []

    if revisions:
        if any(revision is None for revision in revisions):
            raise RuntimeError("The Alembic version table contains an invalid empty revision.")
    else:
        has_password_hash = _validate_unversioned_schema()
        command.stamp(config, "head" if has_password_hash else PRE_PASSWORD_REVISION)

    command.upgrade(config, "head")


if __name__ == "__main__":
    main()
