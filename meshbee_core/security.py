"""Password hashing.

Kept out of the API's auth module because both the API and the seed script hash
passwords, and neither concern is HTTP. No database access, no framework.
"""
import logging

import bcrypt

logger = logging.getLogger(__name__)

BCRYPT_ROUNDS = 12


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica una password contro il suo hash bcrypt"""
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception as e:
        logger.error(f"Errore verifica password: {e}")
        return False


def get_password_hash(password: str) -> str:
    """Genera hash bcrypt di una password"""
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=BCRYPT_ROUNDS))
    return hashed.decode('utf-8')
