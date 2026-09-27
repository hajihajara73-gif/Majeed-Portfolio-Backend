from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    # Upper bound guards against a denial-of-service via enormous Argon2 inputs.
    password: str = Field(min_length=1, max_length=1024)


class LoginResponse(BaseModel):
    """
    Result of stage one.

    When 2FA is enabled no session is issued yet — only a short-lived,
    single-purpose token that can do nothing but complete the second factor.
    """

    status: str  # "authenticated" | "two_factor_required"
    pending_token: str | None = None
    admin: AdminProfile | None = None


class TwoFactorRequest(BaseModel):
    pending_token: str
    code: str = Field(min_length=4, max_length=32)


class AdminProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    full_name: str
    role: str
    totp_enabled: bool
    last_login_at: datetime | None = None


class SessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool = False


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class TwoFactorSetupRequest(BaseModel):
    """
    Begin (or re-begin) 2FA enrolment.

    `current_password` is required only when 2FA is already enabled — moving the
    second factor to a new device is a step-up action, not something a session
    alone should authorise.
    """

    current_password: str | None = Field(default=None, max_length=1024)


class TwoFactorSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class TwoFactorEnableRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class RecoveryCodesResponse(BaseModel):
    codes: list[str]


LoginResponse.model_rebuild()
