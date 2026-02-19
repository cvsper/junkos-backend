#!/usr/bin/env python3
"""
Umuve Database Migration Script

Handles column additions to existing tables and creation of new tables
that db.create_all() won't add to already-existing tables.

Usage:
    python migrate.py          # standalone
    flask db-migrate           # via Flask CLI (registered in server.py)

Safe to run multiple times (idempotent).
Supports both SQLite and PostgreSQL.
"""

import os
import sys
from textwrap import dedent

# ---------------------------------------------------------------------------
# Resolve database URL
# ---------------------------------------------------------------------------

def _resolve_database_url():
    """Return the SQLAlchemy-compatible database URL."""
    url = os.environ.get("DATABASE_URL", "")
    if url:
        # Fix Heroku/Render-style postgres:// -> postgresql://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url
    return "sqlite:///umuve.db"


def _is_sqlite(url):
    return url.startswith("sqlite")


# ---------------------------------------------------------------------------
# Column migration definitions
# ---------------------------------------------------------------------------
# Each entry: (table, column, sql_type_sqlite, sql_type_pg, default_expr | None)
# default_expr is a SQL literal (e.g. "''" or "0.0" or "FALSE" or "NULL")

COLUMN_MIGRATIONS = [
    # User table
    ("users", "referral_code", "VARCHAR(8)", "VARCHAR(8)", "NULL"),

    # Job table
    ("jobs", "before_photos", "TEXT", "JSON", "NULL"),       # JSON stored as TEXT in SQLite
    ("jobs", "after_photos", "TEXT", "JSON", "NULL"),
    ("jobs", "proof_submitted_at", "DATETIME", "TIMESTAMP", "NULL"),
    ("jobs", "operator_id", "VARCHAR(36)", "VARCHAR(36)", "NULL"),
    ("jobs", "delegated_at", "DATETIME", "TIMESTAMP", "NULL"),

    # Contractor table
    ("contractors", "is_operator", "BOOLEAN", "BOOLEAN", "FALSE"),
    ("contractors", "operator_id", "VARCHAR(36)", "VARCHAR(36)", "NULL"),
    ("contractors", "operator_commission_rate", "FLOAT", "FLOAT", "0.15"),

    # Contractor onboarding fields
    ("contractors", "onboarding_status", "VARCHAR(20)", "VARCHAR(20)", "'pending'"),
    ("contractors", "background_check_status", "VARCHAR(20)", "VARCHAR(20)", "'not_started'"),
    ("contractors", "insurance_document_url", "VARCHAR(500)", "VARCHAR(500)", "NULL"),
    ("contractors", "drivers_license_url", "VARCHAR(500)", "VARCHAR(500)", "NULL"),
    ("contractors", "vehicle_registration_url", "VARCHAR(500)", "VARCHAR(500)", "NULL"),
    ("contractors", "insurance_expiry", "DATETIME", "TIMESTAMP", "NULL"),
    ("contractors", "license_expiry", "DATETIME", "TIMESTAMP", "NULL"),
    ("contractors", "onboarding_completed_at", "DATETIME", "TIMESTAMP", "NULL"),
    ("contractors", "rejection_reason", "TEXT", "TEXT", "NULL"),

    # Payment table
    ("payments", "operator_payout_amount", "FLOAT", "FLOAT", "0.0"),

    # Job promo code fields
    ("jobs", "promo_code_id", "VARCHAR(36)", "VARCHAR(36)", "NULL"),
    ("jobs", "discount_amount", "FLOAT", "FLOAT", "0.0"),
    ("jobs", "cancelled_at", "DATETIME", "TIMESTAMP", "NULL"),
    ("jobs", "cancellation_fee", "FLOAT", "FLOAT", "0.0"),
    ("jobs", "rescheduled_count", "INTEGER", "INTEGER", "0"),

    # Job confirmation & volume adjustment (added 2026-02-17)
    ("jobs", "confirmation_code", "VARCHAR(8)", "VARCHAR(8)", "NULL"),
    ("jobs", "volume_adjustment_proposed", "BOOLEAN", "BOOLEAN", "FALSE"),
    ("jobs", "adjusted_volume", "FLOAT", "FLOAT", "NULL"),
    ("jobs", "adjusted_price", "FLOAT", "FLOAT", "NULL"),
    ("jobs", "volume_estimate", "FLOAT", "FLOAT", "NULL"),
    ("jobs", "volume_price", "FLOAT", "FLOAT", "0.0"),
    ("jobs", "item_total", "FLOAT", "FLOAT", "0.0"),

    # Payment fields (added 2026-02-17)
    ("payments", "driver_payout_amount", "FLOAT", "FLOAT", "0.0"),
    ("payments", "payout_status", "VARCHAR(30)", "VARCHAR(30)", "'pending'"),
    ("payments", "payment_status", "VARCHAR(30)", "VARCHAR(30)", "'pending'"),
    ("payments", "tip_amount", "FLOAT", "FLOAT", "0.0"),
    ("payments", "commission", "FLOAT", "FLOAT", "0.0"),
]


# ---------------------------------------------------------------------------
# New table definitions (for tables that may not exist at all)
# ---------------------------------------------------------------------------
# These are the CREATE TABLE IF NOT EXISTS statements for tables added after
# the initial schema.  db.create_all() handles this too, but we include them
# here for standalone usage without importing the full Flask app.

NEW_TABLES_SQLITE = [
    # referrals
    dedent("""\
    CREATE TABLE IF NOT EXISTS referrals (
        id VARCHAR(36) PRIMARY KEY,
        referrer_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        referee_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
        referral_code VARCHAR(8) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        reward_amount FLOAT DEFAULT 10.00,
        created_at DATETIME,
        completed_at DATETIME,
        CONSTRAINT ck_referral_status CHECK (status IN ('pending', 'signed_up', 'completed', 'rewarded'))
    )"""),
    # recurring_bookings
    dedent("""\
    CREATE TABLE IF NOT EXISTS recurring_bookings (
        id VARCHAR(36) PRIMARY KEY,
        customer_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        frequency VARCHAR(20) NOT NULL,
        day_of_week INTEGER,
        day_of_month INTEGER,
        preferred_time VARCHAR(5) NOT NULL DEFAULT '09:00',
        address TEXT NOT NULL,
        lat FLOAT,
        lng FLOAT,
        items TEXT,
        notes TEXT,
        is_active BOOLEAN DEFAULT 1,
        next_scheduled_at DATETIME,
        total_bookings_created INTEGER DEFAULT 0,
        created_at DATETIME,
        updated_at DATETIME,
        CONSTRAINT ck_recurring_frequency CHECK (frequency IN ('weekly', 'biweekly', 'monthly')),
        CONSTRAINT ck_recurring_day_of_week CHECK (day_of_week IS NULL OR (day_of_week >= 0 AND day_of_week <= 6)),
        CONSTRAINT ck_recurring_day_of_month CHECK (day_of_month IS NULL OR (day_of_month >= 1 AND day_of_month <= 28))
    )"""),
    # device_tokens
    dedent("""\
    CREATE TABLE IF NOT EXISTS device_tokens (
        id VARCHAR(36) PRIMARY KEY,
        user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token VARCHAR(512) UNIQUE NOT NULL,
        platform VARCHAR(10) NOT NULL DEFAULT 'ios',
        created_at DATETIME,
        CONSTRAINT ck_device_token_platform CHECK (platform IN ('ios', 'android'))
    )"""),
    # pricing_config
    dedent("""\
    CREATE TABLE IF NOT EXISTS pricing_config (
        key VARCHAR(100) PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at DATETIME
    )"""),
    # operator_invites
    dedent("""\
    CREATE TABLE IF NOT EXISTS operator_invites (
        id VARCHAR(36) PRIMARY KEY,
        operator_id VARCHAR(36) NOT NULL REFERENCES contractors(id) ON DELETE CASCADE,
        invite_code VARCHAR(20) UNIQUE NOT NULL,
        email VARCHAR(255),
        max_uses INTEGER DEFAULT 1,
        use_count INTEGER DEFAULT 0,
        expires_at DATETIME,
        is_active BOOLEAN DEFAULT 1,
        created_at DATETIME
    )"""),
    # promo_codes
    dedent("""\
    CREATE TABLE IF NOT EXISTS promo_codes (
        id VARCHAR(36) PRIMARY KEY,
        code VARCHAR(50) UNIQUE NOT NULL,
        discount_type VARCHAR(20) NOT NULL,
        discount_value FLOAT NOT NULL,
        min_order_amount FLOAT DEFAULT 0.0,
        max_discount FLOAT,
        max_uses INTEGER,
        use_count INTEGER DEFAULT 0,
        expires_at DATETIME,
        is_active BOOLEAN DEFAULT 1,
        created_at DATETIME,
        created_by VARCHAR(36),
        CONSTRAINT ck_promo_discount_type CHECK (discount_type IN ('percentage', 'fixed'))
    )"""),
    # chat_messages
    dedent("""\
    CREATE TABLE IF NOT EXISTS chat_messages (
        id VARCHAR(36) PRIMARY KEY,
        job_id VARCHAR(36) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        sender_id VARCHAR(36) NOT NULL,
        sender_role VARCHAR(20) NOT NULL,
        message TEXT NOT NULL,
        read_at DATETIME,
        created_at DATETIME,
        CONSTRAINT ck_chat_sender_role CHECK (sender_role IN ('customer', 'driver'))
    )"""),
    # reviews
    dedent("""\
    CREATE TABLE IF NOT EXISTS reviews (
        id VARCHAR(36) PRIMARY KEY,
        job_id VARCHAR(36) NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,
        customer_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        contractor_id VARCHAR(36) NOT NULL REFERENCES contractors(id) ON DELETE CASCADE,
        rating INTEGER NOT NULL,
        comment TEXT,
        created_at DATETIME,
        CONSTRAINT ck_review_rating CHECK (rating >= 1 AND rating <= 5)
    )"""),
    # refunds
    dedent("""\
    CREATE TABLE IF NOT EXISTS refunds (
        id VARCHAR(36) PRIMARY KEY,
        payment_id VARCHAR(36) NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
        amount FLOAT NOT NULL,
        reason TEXT,
        stripe_refund_id VARCHAR(255) UNIQUE,
        status VARCHAR(30) NOT NULL DEFAULT 'pending',
        created_at DATETIME,
        CONSTRAINT ck_refund_status CHECK (status IN ('pending', 'succeeded', 'failed', 'cancelled'))
    )"""),
    # webhook_events
    dedent("""\
    CREATE TABLE IF NOT EXISTS webhook_events (
        id VARCHAR(36) PRIMARY KEY,
        stripe_event_id VARCHAR(255) UNIQUE,
        event_type VARCHAR(100) NOT NULL,
        payload TEXT,
        status VARCHAR(20) NOT NULL DEFAULT 'processed',
        error_message TEXT,
        created_at DATETIME
    )"""),
]

NEW_TABLES_PG = [
    # referrals
    dedent("""\
    CREATE TABLE IF NOT EXISTS referrals (
        id VARCHAR(36) PRIMARY KEY,
        referrer_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        referee_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
        referral_code VARCHAR(8) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        reward_amount FLOAT DEFAULT 10.00,
        created_at TIMESTAMP,
        completed_at TIMESTAMP,
        CONSTRAINT ck_referral_status CHECK (status IN ('pending', 'signed_up', 'completed', 'rewarded'))
    )"""),
    # recurring_bookings
    dedent("""\
    CREATE TABLE IF NOT EXISTS recurring_bookings (
        id VARCHAR(36) PRIMARY KEY,
        customer_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        frequency VARCHAR(20) NOT NULL,
        day_of_week INTEGER,
        day_of_month INTEGER,
        preferred_time VARCHAR(5) NOT NULL DEFAULT '09:00',
        address TEXT NOT NULL,
        lat FLOAT,
        lng FLOAT,
        items JSON,
        notes TEXT,
        is_active BOOLEAN DEFAULT FALSE,
        next_scheduled_at TIMESTAMP,
        total_bookings_created INTEGER DEFAULT 0,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        CONSTRAINT ck_recurring_frequency CHECK (frequency IN ('weekly', 'biweekly', 'monthly')),
        CONSTRAINT ck_recurring_day_of_week CHECK (day_of_week IS NULL OR (day_of_week >= 0 AND day_of_week <= 6)),
        CONSTRAINT ck_recurring_day_of_month CHECK (day_of_month IS NULL OR (day_of_month >= 1 AND day_of_month <= 28))
    )"""),
    # device_tokens
    dedent("""\
    CREATE TABLE IF NOT EXISTS device_tokens (
        id VARCHAR(36) PRIMARY KEY,
        user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token VARCHAR(512) UNIQUE NOT NULL,
        platform VARCHAR(10) NOT NULL DEFAULT 'ios',
        created_at TIMESTAMP,
        CONSTRAINT ck_device_token_platform CHECK (platform IN ('ios', 'android'))
    )"""),
    # pricing_config
    dedent("""\
    CREATE TABLE IF NOT EXISTS pricing_config (
        key VARCHAR(100) PRIMARY KEY,
        value JSON NOT NULL,
        updated_at TIMESTAMP
    )"""),
    # operator_invites
    dedent("""\
    CREATE TABLE IF NOT EXISTS operator_invites (
        id VARCHAR(36) PRIMARY KEY,
        operator_id VARCHAR(36) NOT NULL REFERENCES contractors(id) ON DELETE CASCADE,
        invite_code VARCHAR(20) UNIQUE NOT NULL,
        email VARCHAR(255),
        max_uses INTEGER DEFAULT 1,
        use_count INTEGER DEFAULT 0,
        expires_at TIMESTAMP,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP
    )"""),
    # promo_codes
    dedent("""\
    CREATE TABLE IF NOT EXISTS promo_codes (
        id VARCHAR(36) PRIMARY KEY,
        code VARCHAR(50) UNIQUE NOT NULL,
        discount_type VARCHAR(20) NOT NULL,
        discount_value FLOAT NOT NULL,
        min_order_amount FLOAT DEFAULT 0.0,
        max_discount FLOAT,
        max_uses INTEGER,
        use_count INTEGER DEFAULT 0,
        expires_at TIMESTAMP,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP,
        created_by VARCHAR(36),
        CONSTRAINT ck_promo_discount_type CHECK (discount_type IN ('percentage', 'fixed'))
    )"""),
    # chat_messages
    dedent("""\
    CREATE TABLE IF NOT EXISTS chat_messages (
        id VARCHAR(36) PRIMARY KEY,
        job_id VARCHAR(36) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        sender_id VARCHAR(36) NOT NULL,
        sender_role VARCHAR(20) NOT NULL CHECK (sender_role IN ('customer', 'driver')),
        message TEXT NOT NULL,
        read_at TIMESTAMP,
        created_at TIMESTAMP
    )"""),
    # reviews
    dedent("""\
    CREATE TABLE IF NOT EXISTS reviews (
        id VARCHAR(36) PRIMARY KEY,
        job_id VARCHAR(36) NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,
        customer_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        contractor_id VARCHAR(36) NOT NULL REFERENCES contractors(id) ON DELETE CASCADE,
        rating INTEGER NOT NULL,
        comment TEXT,
        created_at TIMESTAMP,
        CONSTRAINT ck_review_rating CHECK (rating >= 1 AND rating <= 5)
    )"""),
    # refunds
    dedent("""\
    CREATE TABLE IF NOT EXISTS refunds (
        id VARCHAR(36) PRIMARY KEY,
        payment_id VARCHAR(36) NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
        amount FLOAT NOT NULL,
        reason TEXT,
        stripe_refund_id VARCHAR(255) UNIQUE,
        status VARCHAR(30) NOT NULL DEFAULT 'pending',
        created_at TIMESTAMP,
        CONSTRAINT ck_refund_status CHECK (status IN ('pending', 'succeeded', 'failed', 'cancelled'))
    )"""),
    # webhook_events
    dedent("""\
    CREATE TABLE IF NOT EXISTS webhook_events (
        id VARCHAR(36) PRIMARY KEY,
        stripe_event_id VARCHAR(255) UNIQUE,
        event_type VARCHAR(100) NOT NULL,
        payload JSON,
        status VARCHAR(20) NOT NULL DEFAULT 'processed',
        error_message TEXT,
        created_at TIMESTAMP
    )"""),
]

# Table names for the new tables (used for reporting)
NEW_TABLE_NAMES = [
    "referrals",
    "recurring_bookings",
    "device_tokens",
    "pricing_config",
    "operator_invites",
    "promo_codes",
    "chat_messages",
    "reviews",
    "refunds",
    "webhook_events",
]


# ---------------------------------------------------------------------------
# Migration engine
# ---------------------------------------------------------------------------

def _get_existing_columns_sqlite(cursor, table):
    """Return set of column names for a table in SQLite."""
    cursor.execute("PRAGMA table_info('{}')".format(table))
    return {row[1] for row in cursor.fetchall()}


def _get_existing_columns_pg(cursor, table):
    """Return set of column names for a table in PostgreSQL."""
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = %s",
        (table,),
    )
    return {row[0] for row in cursor.fetchall()}


def _table_exists_sqlite(cursor, table):
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cursor.fetchone() is not None


def _table_exists_pg(cursor, table):
    cursor.execute(
        "SELECT EXISTS ("
        "  SELECT FROM information_schema.tables "
        "  WHERE table_name = %s"
        ")",
        (table,),
    )
    return cursor.fetchone()[0]


def run_migrations(database_url=None):
    """
    Run all pending migrations.

    Returns a list of action strings describing what was done.
    """
    if database_url is None:
        database_url = _resolve_database_url()

    is_sqlite = _is_sqlite(database_url)
    actions = []

    if is_sqlite:
        import sqlite3
        # Extract the file path from the URL
        # "sqlite:///umuve.db" -> "umuve.db"
        # "sqlite:////absolute/path/db" -> "/absolute/path/db"
        db_path = database_url.replace("sqlite:///", "", 1)
        if not db_path:
            db_path = "umuve.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # ---- Add missing columns to existing tables ----
        for table, column, sql_type, _pg_type, default in COLUMN_MIGRATIONS:
            if not _table_exists_sqlite(cursor, table):
                # Table doesn't exist yet -- it will be created below or by create_all
                continue
            existing = _get_existing_columns_sqlite(cursor, table)
            if column not in existing:
                default_clause = " DEFAULT {}".format(default) if default and default != "NULL" else ""
                stmt = "ALTER TABLE {} ADD COLUMN {} {}{}".format(
                    table, column, sql_type, default_clause
                )
                cursor.execute(stmt)
                actions.append("Added column {}.{}  ({}{})".format(
                    table, column, sql_type, default_clause
                ))

        # ---- Create new tables ----
        for name, ddl in zip(NEW_TABLE_NAMES, NEW_TABLES_SQLITE):
            if not _table_exists_sqlite(cursor, name):
                cursor.execute(ddl)
                actions.append("Created table {}".format(name))
            else:
                actions.append("Table {} already exists -- skipped".format(name))

        conn.commit()
        conn.close()

    else:
        # PostgreSQL
        import psycopg2
        conn = psycopg2.connect(database_url)
        conn.autocommit = True
        cursor = conn.cursor()

        # ---- Add missing columns to existing tables ----
        for table, column, _sqlite_type, sql_type, default in COLUMN_MIGRATIONS:
            if not _table_exists_pg(cursor, table):
                continue
            existing = _get_existing_columns_pg(cursor, table)
            if column not in existing:
                default_clause = " DEFAULT {}".format(default) if default and default != "NULL" else ""
                stmt = "ALTER TABLE {} ADD COLUMN {} {}{}".format(
                    table, column, sql_type, default_clause
                )
                cursor.execute(stmt)
                actions.append("Added column {}.{}  ({}{})".format(
                    table, column, sql_type, default_clause
                ))

        # ---- Create new tables ----
        for name, ddl in zip(NEW_TABLE_NAMES, NEW_TABLES_PG):
            if not _table_exists_pg(cursor, name):
                cursor.execute(ddl)
                actions.append("Created table {}".format(name))
            else:
                actions.append("Table {} already exists -- skipped".format(name))

        cursor.close()
        conn.close()

    if not any("Added" in a or "Created table" in a for a in actions):
        actions.append("Database is up to date -- nothing to do.")

    return actions


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Umuve Database Migration")
    print("=" * 60)

    url = _resolve_database_url()
    db_type = "SQLite" if _is_sqlite(url) else "PostgreSQL"
    safe_url = url if _is_sqlite(url) else url.split("@")[-1] if "@" in url else url
    print("Database: {} ({})".format(safe_url, db_type))
    print("-" * 60)

    actions = run_migrations(url)
    for action in actions:
        print("  -> {}".format(action))

    print("-" * 60)
    print("Migration complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
