from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=100)
    business_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    accepted_terms: bool
    accepted_privacy_policy: bool

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if value.strip() != value:
            raise ValueError("Password must not start or end with spaces")
        if not any(c.islower() for c in value):
            raise ValueError("Password must include a lowercase letter")
        if not any(c.isupper() for c in value):
            raise ValueError("Password must include an uppercase letter")
        if not any(c.isdigit() for c in value):
            raise ValueError("Password must include a number")
        return value


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class BusinessMembershipSummary(BaseModel):
    business_id: UUID
    business_name: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    memberships: list[BusinessMembershipSummary] = []


class MeProfileResponse(BaseModel):
    user_id: UUID
    business_id: UUID
    business_name: str
    role: str
    permissions: list[str] = []


class RefreshTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=20, max_length=512)


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=512)
    new_password: str = Field(min_length=12, max_length=128)
