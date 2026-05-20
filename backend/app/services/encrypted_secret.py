from dataclasses import dataclass
from app.services.token_crypto_service import token_crypto_service


@dataclass
class EncryptedSecret:
    ciphertext: str

    @classmethod
    def from_plaintext(cls, value: str) -> "EncryptedSecret":
        return cls(ciphertext=token_crypto_service.encrypt(value))

    def decrypt(self) -> str:
        return token_crypto_service.decrypt(self.ciphertext)

    def as_storage_value(self) -> str:
        return self.ciphertext
