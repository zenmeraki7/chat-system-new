import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from app.config import settings


class TokenCryptoService:
    _PREFIX = "enc:v1:"

    def __init__(self) -> None:
        self._fernet = Fernet(self._resolve_key())

    def _resolve_key(self) -> bytes:
        configured = (settings.OAUTH_TOKEN_ENCRYPTION_KEY or "").strip()
        if configured:
            return configured.encode("utf-8")
        digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)

    def encrypt(self, plaintext: str) -> str:
        token = self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")
        return f"{self._PREFIX}{token}"

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ciphertext
        if not ciphertext.startswith(self._PREFIX):
            # Backward compatibility for plaintext rows created before encryption rollout.
            return ciphertext
        raw = ciphertext[len(self._PREFIX):]
        try:
            return self._fernet.decrypt(raw.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Invalid encrypted OAuth token payload") from exc


token_crypto_service = TokenCryptoService()
