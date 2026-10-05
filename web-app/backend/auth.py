"""Account storage and opaque, revocable browser sessions."""
import hashlib
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from pwdlib import PasswordHash

SESSION_SECONDS = 7 * 24 * 60 * 60
PASSWORDS = PasswordHash.recommended()
# Verify a hash even when the username does not exist.
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))


def username(value):
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", value):
        raise ValueError("Identifiant invalide : utilise 1 à 32 lettres, chiffres, tirets ou soulignements.")
    return value


def validate_password(value):
    if not 6 <= len(value) <= 256:
        raise ValueError("Le mot de passe doit contenir entre 6 et 256 caractères.")


class Accounts:
    def __init__(self, directory, clock=time.time):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.path = self.directory / "accounts.sqlite3"
        self.clock = clock
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL, password_hash TEXT NOT NULL,
                    must_change_password INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL
                    REFERENCES users(id) ON DELETE CASCADE, expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS login_failures (
                    scope TEXT PRIMARY KEY, attempts INTEGER NOT NULL, started_at REAL NOT NULL
                );
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            with db:
                yield db
        finally:
            db.close()

    def user(self, name):
        with self.connection() as db:
            result = db.execute("SELECT * FROM users WHERE username = ?", (username(name),)).fetchone()
        if result is None:
            raise ValueError("Compte introuvable.")
        return dict(result)

    def create(self, name, display_name, password, must_change=True):
        name = username(name)
        validate_password(password)
        display_name = display_name.strip()
        if not 1 <= len(display_name) <= 80:
            raise ValueError("Le nom affiché doit contenir entre 1 et 80 caractères.")
        identifier = uuid.uuid4().hex
        password_hash = PASSWORDS.hash(password)
        try:
            with self.connection() as db:
                db.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                           (identifier, name, display_name, password_hash, int(must_change)))
        except sqlite3.IntegrityError as error:
            raise ValueError("Ce compte existe déjà.") from error
        return self.user(name)

    @staticmethod
    def public(user):
        return {"username": user["username"], "display_name": user["display_name"],
                "must_change_password": bool(user["must_change_password"])}

    def login(self, name, password, address):
        name = name.strip().lower()[:256]
        now = self.clock()
        # Independent per-address and per-account limits resist username rotation.
        scopes = ["ip:" + address, "user:" + name]
        with self.connection() as db:
            db.execute("DELETE FROM login_failures WHERE started_at <= ?", (now - 900,))
            for scope in scopes:
                row = db.execute("SELECT attempts FROM login_failures WHERE scope = ?", (scope,)).fetchone()
                if row is not None and row["attempts"] >= 10:
                    raise PermissionError("Trop de tentatives. Réessaie dans quinze minutes.")
            row = db.execute("SELECT * FROM users WHERE username = ?", (name,)).fetchone()
        valid = PASSWORDS.verify(password, row["password_hash"] if row else DUMMY_HASH)
        if not row or not valid:
            with self.connection() as db:
                for scope in scopes:
                    db.execute("""INSERT INTO login_failures VALUES (?, 1, ?)
                        ON CONFLICT(scope) DO UPDATE SET attempts = attempts + 1""", (scope, now))
            return None
        with self.connection() as db:
            db.execute("DELETE FROM login_failures WHERE scope IN (?, ?)", scopes)
        return self.issue_session(dict(row))

    def issue_session(self, user):
        token = secrets.token_urlsafe(32)
        now = self.clock()
        with self.connection() as db:
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            db.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                       (self.digest(token), user["id"], now + SESSION_SECONDS))
        return user, token

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def resolve(self, token):
        if not token or len(token) > 256:
            return None
        with self.connection() as db:
            row = db.execute("""SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id
                WHERE token_hash = ? AND expires_at > ?""", (self.digest(token), self.clock())).fetchone()
        return dict(row) if row else None

    def logout(self, token):
        if token:
            with self.connection() as db:
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (self.digest(token),))

    def set_password(self, identifier, password, must_change=False):
        validate_password(password)
        password_hash = PASSWORDS.hash(password)
        with self.connection() as db:
            db.execute("UPDATE users SET password_hash = ?, must_change_password = ? WHERE id = ?",
                       (password_hash, int(must_change), identifier))
            db.execute("DELETE FROM sessions WHERE user_id = ?", (identifier,))
        if not must_change:
            (self.directory / "bootstrap" / (identifier + ".txt")).unlink(missing_ok=True)

    def progress_path(self, identifier):
        # IDs are generated on the server, never derived from a request path.
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError("Identifiant de compte invalide.")
        return self.directory / "users" / identifier / "progress.json"
