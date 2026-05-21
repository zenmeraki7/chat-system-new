from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
from dataclasses import dataclass
from app.repositories.business_repo import BusinessRepository
from app.repositories.user_auth_repo import UserAuthRepository
from app.core.security import hash_password, verify_password, create_access_token
from app.core.exceptions import ConflictException, UnauthorizedException, BadRequestException
from app.models.business import Business
from app.models.business_domains import BusinessLegalAcceptance, BusinessEvent
from app.config import settings
from app.services.audit_log_service import AuditLogService


@dataclass(frozen=True)
class AuthLoginResult:
    access_token: str
    memberships: list[dict]


class AuthService:
    def __init__(self, db: AsyncSession):
        self.repo = BusinessRepository(db)
        self.user_auth_repo = UserAuthRepository(db)
        self.audit = AuditLogService(db)

    async def register(
        self,
        *,
        business_name: str,
        email: str,
        password: str,
        accepted_terms: bool,
        accepted_privacy_policy: bool,
    ) -> tuple[Business, str]:
        if not accepted_terms or not accepted_privacy_policy:
            raise BadRequestException("Terms and privacy policy acceptance is required")
        async with self.repo.db.begin():
            existing = await self.user_auth_repo.get_user_by_normalized_email(email)
            if existing:
                raise ConflictException("Email is already registered")

            business, raw_api_key = await self.repo.create_business_with_defaults(
                name=business_name,
                email=email,
                password_hash=hash_password(password),
            )
            business = await self.repo.get_business_with_profile(business.id)
            membership = business.memberships[0] if business and business.memberships else None
            if membership:
                self.repo.db.add(
                    BusinessLegalAcceptance(
                        business_id=business.id,
                        user_id=membership.user_id,
                        document_type="signup_legal_bundle",
                        document_version=getattr(settings, "TERMS_VERSION", "v1"),
                    )
                )
                self.repo.db.add(
                    BusinessEvent(
                        business_id=business.id,
                        event_type="business.created",
                        actor_user_id=membership.user_id,
                    )
                )
                await self.repo.db.flush()
            await self.audit.write(
                action="auth.register",
                resource_type="business",
                business_id=business.id,
                user_id=membership.user_id if membership else None,
                actor_type="user",
                actor_id=str(membership.user_id) if membership else None,
                resource_id=str(business.id),
                details={"email": email.strip().lower()},
            )
            return business, raw_api_key

    async def login(self, email: str, password: str) -> AuthLoginResult:
        async with self.repo.db.begin():
            auth_record = await self.user_auth_repo.get_auth_record_by_email(email)
            if not auth_record or not verify_password(password, auth_record.password_hash):
                await self.audit.write(
                    action="auth.login",
                    resource_type="user",
                    status="failed",
                    actor_type="user",
                    actor_id=email.strip().lower(),
                    details={"reason": "invalid_credentials"},
                )
                raise UnauthorizedException("Invalid email or password")
            user = await self.user_auth_repo.get_user_by_normalized_email(email)
            business = await self.repo.get_business_with_profile(auth_record.business_id)
            membership = business.memberships[0] if business and business.memberships else None
            if not user or not business:
                raise UnauthorizedException("Invalid email or password")
            if auth_record.password_rehash_required:
                user.password_hash = hash_password(password)
                user.password_rehash_required = False
                user.password_changed_at = datetime.now(timezone.utc)
                await self.repo.db.flush()
            if auth_record.business_status != "active":
                await self.audit.write(
                    action="auth.login",
                    resource_type="business",
                    status="failed",
                    business_id=business.id,
                    user_id=user.id,
                    actor_type="user",
                    actor_id=str(user.id),
                    resource_id=str(business.id),
                    details={"reason": "business_inactive"},
                )
                raise UnauthorizedException("Account is deactivated")

            await self.audit.write(
                action="auth.login",
                resource_type="business",
                business_id=business.id,
                user_id=user.id,
                actor_type="user",
                actor_id=str(user.id),
                resource_id=str(business.id),
            )
            return AuthLoginResult(
                access_token=create_access_token(subject=f"{business.id}:{user.id}"),
                memberships=[
                    {
                        "business_id": business.id,
                        "business_name": business.name,
                        "role": (membership.role_code if membership and getattr(membership, "role_code", None) else "member"),
                    }
                ],
            )
