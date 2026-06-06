from uuid import UUID
from pydantic import BaseModel,EmailStr,Field
from app.models.user import UserRole
from app.schemas.common import Identified
class UserCreate(BaseModel): email:EmailStr; password:str=Field(min_length=8); full_name:str=""; role:UserRole=UserRole.user
class UserUpdate(BaseModel): email:EmailStr|None=None; full_name:str|None=None; is_active:bool|None=None
class RoleUpdate(BaseModel): role:UserRole
class UserRead(Identified): email:EmailStr; full_name:str; role:UserRole; is_active:bool
class LoginRequest(BaseModel): email:EmailStr; password:str
class RefreshRequest(BaseModel): refresh_token:str
class TokenPair(BaseModel): access_token:str; refresh_token:str; token_type:str="bearer"
