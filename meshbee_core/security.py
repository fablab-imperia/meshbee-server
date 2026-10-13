"""Password and token hashing.

Kept out of the API's auth module because both the API and the seed script hash
passwords, and neither concern is HTTP. No database access, no framework.
"""

import hashlib
import logging

import bcrypt

logger = logging.getLogger(__name__)

BCRYPT_ROUNDS = 12


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica una password contro il suo hash bcrypt"""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except Exception as e:
        logger.exception(f"Errore verifica password: {e}")
        return False


def get_password_hash(password: str) -> str:
    """Genera hash bcrypt di una password"""
    hashed = bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    )
    return hashed.decode("utf-8")


def hash_token(token: str) -> str:
    """
    The SHA-256 of a refresh token, as stored in `token_sessione`.

    A plain digest, not bcrypt: the token is a long random JWT, not a guessable
    password, and the hash must be deterministic so a session can be looked up by it.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
