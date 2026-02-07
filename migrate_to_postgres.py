#!/usr/bin/env python3
"""
Migration script to copy data from SQLite to PostgreSQL
Usage: python migrate_to_postgres.py
"""

import os
import sys
import sqlite3
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()


def connect_sqlite(db_path='junkos.db'):
    """Connect to SQLite database"""
    if not os.path.exists(db_path):
        print(f"❌ SQLite database not found: {db_path}")
        sys.exit(1)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def connect_postgres():
    """Connect to PostgreSQL database"""
    database_url = os.environ.get('DATABASE_URL')
    
    if not database_url:
        print("❌ DATABASE_URL environment variable not set")
        print("   Set it with: export DATABASE_URL='postgresql://user:pass@host:port/dbname'")
        sys.exit(1)
    
    # Fix postgres:// to postgresql:// for psycopg2
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    try:
        conn = psycopg2.connect(database_url)
        return conn
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}")
        sys.exit(1)


def migrate_table(sqlite_conn, postgres_conn, table_name, columns):
    """Migrate a single table from SQLite to PostgreSQL"""
    print(f"\n📦 Migrating table: {table_name}")
    
    # Fetch data from SQLite
    sqlite_cursor = sqlite_conn.cursor()
    sqlite_cursor.execute(f"SELECT * FROM {table_name}")
    rows = sqlite_cursor.fetchall()
    
    if not rows:
        print(f"   ⚠️  No data found in {table_name}")
        return 0
    
    # Prepare data for PostgreSQL
    data = [tuple(row) for row in rows]
    
    # Insert into PostgreSQL
    postgres_cursor = postgres_conn.cursor()
    
    # Get column names (excluding id for auto-increment)
    cols_without_id = [col for col in columns if col != 'id']
    placeholders = ', '.join(['%s'] * len(cols_without_id))
    
    insert_query = f"""
        INSERT INTO {table_name} ({', '.join(cols_without_id)})
        VALUES ({placeholders})
    """
    
    try:
        for row in data:
            # Skip the id column (first column)
            row_data = tuple(row)[1:]
            postgres_cursor.execute(insert_query, row_data)
        
        postgres_conn.commit()
        print(f"   ✅ Migrated {len(rows)} rows")
        return len(rows)
    
    except Exception as e:
        postgres_conn.rollback()
        print(f"   ❌ Error migrating {table_name}: {e}")
        return 0


def reset_sequences(postgres_conn, tables):
    """Reset PostgreSQL sequences after migration"""
    print("\n🔄 Resetting sequences...")
    cursor = postgres_conn.cursor()
    
    for table in tables:
        try:
            cursor.execute(f"""
                SELECT setval(
                    pg_get_serial_sequence('{table}', 'id'),
                    (SELECT MAX(id) FROM {table})
                )
            """)
            print(f"   ✅ Reset sequence for {table}")
        except Exception as e:
            print(f"   ⚠️  Could not reset sequence for {table}: {e}")
    
    postgres_conn.commit()


def verify_migration(sqlite_conn, postgres_conn, table_name):
    """Verify row counts match between databases"""
    sqlite_cursor = sqlite_conn.cursor()
    postgres_cursor = postgres_conn.cursor()
    
    sqlite_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    sqlite_count = sqlite_cursor.fetchone()[0]
    
    postgres_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    postgres_count = postgres_cursor.fetchone()[0]
    
    if sqlite_count == postgres_count:
        print(f"   ✅ {table_name}: {sqlite_count} rows (verified)")
        return True
    else:
        print(f"   ❌ {table_name}: SQLite={sqlite_count}, PostgreSQL={postgres_count} (MISMATCH)")
        return False


def main():
    print("🚀 JunkOS Database Migration: SQLite → PostgreSQL\n")
    
    # Get database path
    db_path = os.environ.get('DATABASE_PATH', 'junkos.db')
    
    # Connect to databases
    print("📡 Connecting to databases...")
    sqlite_conn = connect_sqlite(db_path)
    postgres_conn = connect_postgres()
    print("   ✅ Connected to both databases\n")
    
    # Define tables and their columns (excluding id)
    tables = {
        'customers': ['name', 'email', 'phone', 'created_at'],
        'services': ['name', 'description', 'base_price', 'unit', 'created_at'],
        'bookings': ['customer_id', 'address', 'zip_code', 'services', 'photos', 
                     'scheduled_datetime', 'estimated_price', 'status', 'notes', 'created_at']
    }
    
    # Migrate each table
    total_rows = 0
    for table_name, columns in tables.items():
        rows_migrated = migrate_table(sqlite_conn, postgres_conn, table_name, columns)
        total_rows += rows_migrated
    
    # Reset sequences
    reset_sequences(postgres_conn, list(tables.keys()))
    
    # Verify migration
    print("\n✅ Verifying migration...")
    all_verified = True
    for table_name in tables.keys():
        if not verify_migration(sqlite_conn, postgres_conn, table_name):
            all_verified = False
    
    # Close connections
    sqlite_conn.close()
    postgres_conn.close()
    
    print("\n" + "="*60)
    if all_verified:
        print(f"✅ Migration completed successfully!")
        print(f"   Total rows migrated: {total_rows}")
    else:
        print(f"⚠️  Migration completed with warnings")
        print(f"   Please verify your data manually")
    print("="*60 + "\n")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Migration cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Migration failed: {e}")
        sys.exit(1)
