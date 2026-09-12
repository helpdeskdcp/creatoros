import uuid

from pydantic import BaseModel, ConfigDict, EmailStr

from app.modules.users.models import UserRole


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: UserRole
    is_active: bool


class UpdateUserRoleRequest(BaseModel):
    role: UserRole


class UpdateUserActiveRequest(BaseModel):
    is_active: bool
