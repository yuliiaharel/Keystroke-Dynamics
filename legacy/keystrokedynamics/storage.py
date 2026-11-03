"""Shared SQLite access for digraph statistics.

One table for every user, keyed by (username, digraph_id), instead of
one dynamically-named table per user. The old design built SQL by
string-concatenating the username straight into CREATE TABLE/SELECT/
INSERT statements -- table/column names can't be bound parameters in
SQLite (or most SQL dialects), so that username was a direct SQL
injection vector. Here username and digraph_id are always bound
parameters, never spliced into the query text.
"""

import sqlite3

DB_PATH = "keystroke.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS digraphs (
    username TEXT NOT NULL,
    digraph_id TEXT NOT NULL,
    expected_value REAL NOT NULL,
    variance REAL NOT NULL,
    frequency INTEGER NOT NULL,
    PRIMARY KEY (username, digraph_id)
)
"""


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(_SCHEMA)
    return conn


def normalize_username(username):
    return username.replace(" ", "_")


def user_exists(username):
    """Whether username has any stored profile at all."""
    username = normalize_username(username)
    conn = _connect()
    try:
        return _has_rows(conn, username)
    finally:
        conn.close()


def _has_rows(conn, username):
    cur = conn.execute("SELECT 1 FROM digraphs WHERE username = ? LIMIT 1", (username,))
    return cur.fetchone() is not None


def get_digraph(username, digraph_id):
    """Returns (expected_value, variance) for one digraph.

    (None, None) if username has no profile at all (a brand new
    user). (0, 0) if username has a profile but never recorded this
    particular digraph -- matches the original code's distinction
    between "new user" and "new digraph".
    """
    username = normalize_username(username)
    conn = _connect()
    try:
        if not _has_rows(conn, username):
            return None, None
        cur = conn.execute(
            "SELECT expected_value, variance FROM digraphs WHERE username = ? AND digraph_id = ?",
            (username, digraph_id),
        )
        row = cur.fetchone()
        return (row[0], row[1]) if row is not None else (0, 0)
    finally:
        conn.close()


def count_digraphs(username):
    username = normalize_username(username)
    conn = _connect()
    try:
        cur = conn.execute("SELECT COUNT(*) FROM digraphs WHERE username = ?", (username,))
        return cur.fetchone()[0]
    finally:
        conn.close()


def save_profile(username, items):
    """Stores a brand-new profile. items: iterable of
    (digraph_id, expected_value, variance, frequency).

    Returns False without writing anything if username already has a
    profile (matches the original "don't overwrite an existing user"
    behavior).
    """
    username = normalize_username(username)
    conn = _connect()
    try:
        if _has_rows(conn, username):
            return False
        for digraph_id, expected_value, variance, frequency in items:
            conn.execute(
                "INSERT INTO digraphs (username, digraph_id, expected_value, variance, frequency) "
                "VALUES (?, ?, ?, ?, ?)",
                (username, digraph_id, expected_value, variance, frequency),
            )
        conn.commit()
        return True
    finally:
        conn.close()
