from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class UserBase(BaseModel):
    github_username: str
    email: str

class UserCreate(UserBase):
    pass

class UserUpdate(BaseModel):
    github_username: Optional[str] = None
    email: Optional[str] = None

class UserInDBBase(UserBase):
    user_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class User(UserInDBBase):
    pass

class UserLogin(BaseModel):
    email: str = Field(..., description="The email of the user")
    password: str = Field(..., description="The password of the user")


class UserRegister(BaseModel):
    github_username: str = Field(..., description="The Github username of the user")
    email: str = Field(..., description="The email of the user")
    password: str = Field(..., description="The password of the user")    