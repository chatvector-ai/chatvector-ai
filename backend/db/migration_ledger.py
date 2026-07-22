"""Compare numbered SQL migration files with the database migration ledger."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


MIGRATIONS_DIR = Path(__file__).resolve().parent / "init"
LEDGER_BOOTSTRAP_FILENAME = "008_schema_migrations.sql"
BASELINE_MIGRATION_FILENAMES = (
    "001_init.sql",
    "002_dimensionless_vector.sql",
    "003_atomic_delete.sql",
    "004_chat_history.sql",
    "004_hybrid_retrieval.sql",
    "005_api_keys.sql",
    "006_tenant_fk_and_backfill.sql",
    "007_sessions.sql",
    LEDGER_BOOTSTRAP_FILENAME,
)


@dataclass(frozen=True)
class MigrationDrift:
    """Differences between this checkout and the database migration ledger."""

    missing_from_ledger: tuple[str, ...] = ()
    unknown_to_checkout: tuple[str, ...] = ()

    @property
    def is_current(self) -> bool:
        return not self.missing_from_ledger and not self.unknown_to_checkout


class MigrationLedgerError(RuntimeError):
    """Base class for operator-actionable migration ledger failures."""


class MigrationLedgerMissingError(MigrationLedgerError):
    """Raised when migration 008 has not created the ledger table."""


class MigrationLedgerSchemaError(MigrationLedgerError):
    """Raised when the ledger exists but does not match its required schema."""


class MigrationFilesMissingError(MigrationLedgerError):
    """Raised when the application artifact omits its migration SQL bundle."""


class MigrationDriftError(MigrationLedgerError):
    """Raised when this checkout contains migrations absent from the ledger."""


def migration_filenames(migrations_dir: Path = MIGRATIONS_DIR) -> tuple[str, ...]:
    """Return migration filenames in the same lexical order used by CI/Docker."""

    return tuple(sorted(path.name for path in migrations_dir.glob("*.sql") if path.is_file()))


def compare_migration_filenames(
    expected: Iterable[str], applied: Iterable[str]
) -> MigrationDrift:
    """Return deterministic filesystem-vs-ledger differences."""

    expected_set = set(expected)
    applied_set = set(applied)
    return MigrationDrift(
        missing_from_ledger=tuple(sorted(expected_set - applied_set)),
        unknown_to_checkout=tuple(sorted(applied_set - expected_set)),
    )


def validate_migration_ledger(
    applied_filenames: Iterable[str] | None,
    migrations_dir: Path = MIGRATIONS_DIR,
) -> MigrationDrift:
    """Validate migration files and raise for missing ledger state.

    ``None`` represents a missing ``schema_migrations`` table. Ledger rows that
    do not exist in this checkout are returned as advisory drift because they
    commonly mean the database is newer than the running application.
    """

    try:
        expected = migration_filenames(migrations_dir)
    except OSError as exc:
        raise MigrationFilesMissingError(
            f"Application migration files cannot be read from {migrations_dir}. "
            "Ensure backend/db/init/*.sql is included in the deployed artifact."
        ) from exc

    missing_bundle_files = tuple(
        sorted(set(BASELINE_MIGRATION_FILENAMES) - set(expected))
    )
    if missing_bundle_files:
        missing = ", ".join(missing_bundle_files)
        raise MigrationFilesMissingError(
            f"Application migration bundle is incomplete at {migrations_dir}: "
            f"required files are missing: {missing}."
        )

    if applied_filenames is None:
        raise MigrationLedgerMissingError(
            "Database migration ledger is missing. Apply any pending historical "
            f"migrations first, then apply {LEDGER_BOOTSTRAP_FILENAME} with "
            "`psql -v ON_ERROR_STOP=1 -f <migration-file>` before starting "
            "ChatVector. See DEVELOPMENT.md#upgrading-an-existing-database."
        )

    drift = compare_migration_filenames(expected, applied_filenames)
    if drift.missing_from_ledger:
        missing = ", ".join(drift.missing_from_ledger)
        baseline_set = set(BASELINE_MIGRATION_FILENAMES)
        missing_historical = tuple(
            filename
            for filename in drift.missing_from_ledger
            if filename in baseline_set and filename != LEDGER_BOOTSTRAP_FILENAME
        )
        bootstrap_missing = LEDGER_BOOTSTRAP_FILENAME in drift.missing_from_ledger
        missing_future = tuple(
            filename
            for filename in drift.missing_from_ledger
            if filename not in baseline_set
        )

        guidance: list[str] = []
        if missing_historical:
            historical = ", ".join(missing_historical)
            guidance.append(
                "Missing pre-ledger rows do not prove that their historical SQL is "
                f"unapplied ({historical}). Verify each migration's schema effects or "
                "deployment history, apply only genuinely missing historical SQL in "
                "lexical order, then rerun 008_schema_migrations.sql to restore the "
                "baseline ledger rows."
            )
        elif bootstrap_missing:
            guidance.append(
                "Rerun 008_schema_migrations.sql to restore its idempotent baseline "
                "ledger rows."
            )

        if missing_future:
            future = ", ".join(missing_future)
            guidance.append(
                f"Apply the missing post-ledger migration files in lexical order "
                f"({future}) with `psql -v ON_ERROR_STOP=1 -f <migration-file>`; "
                "each file must record its own ledger row."
            )

        message = (
            "Database migration drift detected. Migration files missing from "
            f"schema_migrations: {missing}. "
            + " ".join(guidance)
            + " Do not replay 001_init.sql on a populated database. Inspect the "
            "ledger with `SELECT filename, applied_at FROM "
            "public.schema_migrations ORDER BY filename;`. See "
            "DEVELOPMENT.md#upgrading-an-existing-database."
        )
        if drift.unknown_to_checkout:
            unknown = ", ".join(drift.unknown_to_checkout)
            message += f" Ledger entries absent from this checkout: {unknown}."
        raise MigrationDriftError(message)

    return drift
