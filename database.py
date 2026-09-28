# sqlite connection handling + schema setup

import hashlib
import os
import secrets
import sqlite3
from datetime import datetime

from flask import g

DB_PATH = os.path.join(os.path.dirname(__file__), "seating.db")

ADMIN_USERNAME = "admin"
ADMIN_DEFAULT_PASSWORD = "admin"  # seeded account must change this on first login


def get_db():
    # one connection per request, cached on flask's g
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db:
        db.close()


def _hash_password(password: str) -> str:
    # mirrors auth.hash_password exactly (same salt$hash format) — duplicated
    # here rather than imported, since auth.py imports get_db from this module
    # and importing back would create a circular import
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"{salt}${dk.hex()}"


def init_db():
    # run once at startup, creates tables if they don't exist yet
    db = sqlite3.connect(DB_PATH)

    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            username              TEXT    UNIQUE NOT NULL,
            email                 TEXT    UNIQUE NOT NULL,
            password              TEXT    NOT NULL,
            role                  TEXT    NOT NULL DEFAULT 'planner',
            force_password_change INTEGER NOT NULL DEFAULT 0,
            created_at            TEXT    NOT NULL
        )
    """)

    # migration for DBs created before force_password_change existed —
    # CREATE TABLE IF NOT EXISTS is a no-op on an existing table, so this
    # covers upgrades from an older seating.db
    try:
        db.execute(
            "ALTER TABLE users ADD COLUMN force_password_change INTEGER NOT NULL DEFAULT 0"
        )
    except sqlite3.OperationalError:
        pass  # column already there

    db.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            token      TEXT    NOT NULL,
            created_at TEXT    NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS venues (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            name        TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            venue_type  TEXT    NOT NULL DEFAULT 'classroom',
            rows        INTEGER NOT NULL,
            cols        INTEGER NOT NULL,
            layout_json TEXT    NOT NULL,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            name            TEXT    NOT NULL,
            group_name      TEXT    NOT NULL DEFAULT '',
            needs_front_row INTEGER NOT NULL DEFAULT 0,
            needs_aisle     INTEGER NOT NULL DEFAULT 0,
            notes           TEXT    NOT NULL DEFAULT '',
            created_at      TEXT    NOT NULL,
            UNIQUE(user_id, name),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS arrangements (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id           INTEGER NOT NULL,
            venue_id          INTEGER,
            name              TEXT    NOT NULL,
            status            TEXT    NOT NULL DEFAULT 'unsolved',
            participants_json TEXT    NOT NULL DEFAULT '[]',
            constraints_json  TEXT    NOT NULL DEFAULT '[]',
            result_json       TEXT,
            created_at        TEXT    NOT NULL,
            updated_at        TEXT    NOT NULL,
            FOREIGN KEY(user_id)  REFERENCES users(id),
            FOREIGN KEY(venue_id) REFERENCES venues(id) ON DELETE SET NULL
        )
    """)

    # seed the built-in admin account on first run — fixed credentials,
    # forced to change the password on first login
    existing_admin = db.execute(
        "SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)
    ).fetchone()
    if not existing_admin:
        db.execute(
            """INSERT INTO users
               (username, email, password, role, force_password_change, created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                ADMIN_USERNAME, "admin@seatwise.local",
                _hash_password(ADMIN_DEFAULT_PASSWORD),
                "admin", 1, datetime.utcnow().isoformat(),
            ),
        )

    db.commit()
    db.close()
