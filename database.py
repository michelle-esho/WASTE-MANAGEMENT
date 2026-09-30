import sqlite3

DATABASE_NAME = "waste_management.db"


def get_connection():
    connection = sqlite3.connect(DATABASE_NAME)
    connection.row_factory = sqlite3.Row
    return connection


def add_column_if_missing(cursor, table_name, column_name, column_definition):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [column[1] for column in cursor.fetchall()]

    if column_name not in columns:
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
        )


def create_database():
    connection = get_connection()
    cursor = connection.cursor()

    # ==============================
    # USERS TABLE
    # ==============================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            created_at TEXT
        )
    """)

    # Add missing columns to old users table
    add_column_if_missing(
        cursor,
        "users",
        "full_name",
        "TEXT"
    )

    add_column_if_missing(
        cursor,
        "users",
        "created_at",
        "TEXT"
    )

    # ==============================
    # WASTE REPORTS TABLE
    # ==============================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS waste_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            location TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            reported_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY (user_id)
            REFERENCES users(id)
        )
    """)

    # Add missing columns to old waste_reports table
    add_column_if_missing(
        cursor,
        "waste_reports",
        "user_id",
        "INTEGER"
    )

    add_column_if_missing(
        cursor,
        "waste_reports",
        "updated_at",
        "TEXT"
    )

    # ==============================
    # ACTIVITY LOGS TABLE
    # ==============================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id)
            REFERENCES users(id)
        )
    """)

    connection.commit()
    connection.close()


if __name__ == "__main__":
    create_database()
    print("Database updated successfully.")
    