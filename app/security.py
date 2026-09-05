import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone

from app.config import JWT_EXPIRE_MINUTES, JWT_SECRET


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 600_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(iterations)
        ).hex()
        return hmac.compare_digest(candidate, expected)
    except (ValueError, TypeError):
        return False


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64encode(
        json.dumps(
            {
                "sub": user_id,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=JWT_EXPIRE_MINUTES)).timestamp()),
            },
            separators=(",", ":"),
        ).encode()
    )
    signed = f"{header}.{payload}".encode()
    signature = _b64encode(hmac.new(JWT_SECRET.encode(), signed, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def decode_access_token(token: str) -> str | None:
    try:
        header, payload, signature = token.split(".")
        signed = f"{header}.{payload}".encode()
        expected = _b64encode(hmac.new(JWT_SECRET.encode(), signed, hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        decoded_header = json.loads(_b64decode(header))
        decoded_payload = json.loads(_b64decode(payload))
        if decoded_header != {"alg": "HS256", "typ": "JWT"}:
            return None
        if not isinstance(decoded_payload.get("sub"), str):
            return None
        if int(decoded_payload["exp"]) <= int(datetime.now(timezone.utc).timestamp()):
            return None
        return decoded_payload["sub"]
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
