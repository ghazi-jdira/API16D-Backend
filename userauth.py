"""
Server-side username/password auth helpers (standard-library only).

- Passwords are stored as PBKDF2-HMAC-SHA256 hashes (per-user random salt) in
  users.json -- never in plaintext, never sent to the client.
- On successful login the server issues a short-lived HMAC-signed token. Every
  protected request carries it; the server re-verifies the signature + expiry.

Manage users with manage_users.py. The signing secret comes from the SECRET_KEY
environment variable.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

_USERS_PATH = os.path.join(os.path.dirname(__file__), "users.json")
_PBKDF2_ITERATIONS = 200_000


# ---- password hashing ----------------------------------------------------
def hash_password(password: str, salt: str = None, iterations: int = _PBKDF2_ITERATIONS) -> dict:
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                             bytes.fromhex(salt), iterations)
    return {"salt": salt, "hash": dk.hex(), "iterations": iterations}


def verify_password(password: str, record: dict) -> bool:
    if not record:
        return False
    iterations = int(record.get("iterations", _PBKDF2_ITERATIONS))
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                             bytes.fromhex(record["salt"]), iterations)
    return hmac.compare_digest(dk.hex(), record["hash"])


# ---- user store ----------------------------------------------------------
def load_users() -> dict:
    if not os.path.exists(_USERS_PATH):
        return {}
    with open(_USERS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_users(users: dict) -> None:
    with open(_USERS_PATH, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)
        f.write("\n")


def find_user(username: str, users: dict = None):
    users = users if users is not None else load_users()
    return users.get((username or "").strip().lower())


# ---- signed tokens (compact HMAC-signed, JWT-like) -----------------------
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(username: str, secret: str, ttl_seconds: int = 12 * 3600) -> str:
    payload = {"sub": username, "exp": int(time.time()) + ttl_seconds}
    p64 = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(secret.encode("utf-8"), p64.encode("ascii"), hashlib.sha256).digest()
    return p64 + "." + _b64(sig)


def verify_token(token: str, secret: str):
    """Return the username if the token is valid and unexpired, else None."""
    try:
        p64, s64 = token.split(".", 1)
        expected = _b64(hmac.new(secret.encode("utf-8"),
                                 p64.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, s64):
            return None
        payload = json.loads(_unb64(p64))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload.get("sub")
    except Exception:
        return None
