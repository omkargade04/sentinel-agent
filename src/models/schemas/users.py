from uuid import UUID
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional

class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    pass

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None

class UserInDBBase(UserBase):
    user_id: UUID
    supabase_user_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class User(UserInDBBase):
    pass

class UserLogin(BaseModel):
    email: EmailStr = Field(..., description="The email of the user")
    password: str = Field(..., description="The password of the user")


class UserRegister(BaseModel):
    email: EmailStr = Field(..., description="The email of the user")
    password: str = Field(..., description="The password of the user")