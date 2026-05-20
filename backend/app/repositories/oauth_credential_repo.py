from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.base import SecretRepository
from app.models.business_domains import OAuthCredential
from app.core.security import hash_token
from app.services.token_crypto_service import token_crypto_service


class OAuthCredentialRepository(SecretRepository[OAuthCredential]):
    def __init__(self, db: AsyncSession):
        super().__init__(OAuthCredential, db)

    async def store_encrypted_access_token(
        self,
        *,
        business_id: UUID,
        provider: str,
        access_token: str,
        credential_owner_type: str = "business",
        credential_owner_id: str | None = None,
        scopes: list[str] | None = None,
    ) -> OAuthCredential:
        row = OAuthCredential(
            business_id=business_id,
            provider=provider,
            credential_owner_type=credential_owner_type,
            credential_owner_id=credential_owner_id or str(business_id),
            access_token_ciphertext=token_crypto_service.encrypt(access_token),
            token_hash=hash_token(access_token),
            scopes=scopes or [],
        )
        self.db.add(row)
        await self.db.flush()
        return row
