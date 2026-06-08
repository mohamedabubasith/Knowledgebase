from uuid import UUID
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import hash_password
from app.models import User, UserRole
from app.repositories.user_repo import UserRepo
from app.schemas.user import UserCreate, UserUpdate


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.users = UserRepo(db)

    async def list_users(self) -> list[User]:
        return await self.users.list_all()

    async def create(self, body: UserCreate) -> User:
        if await self.users.get_by_email(body.email):
            raise HTTPException(409, "Email already exists")
        user = await self.users.create(
            email=body.email,
            hashed_password=hash_password(body.password),
            full_name=body.full_name,
            role=body.role,
        )
        await self.db.commit()
        return user

    async def get(self, id: UUID) -> User:
        user = await self.users.get_by_id(id)
        if not user:
            raise HTTPException(404, "User not found")
        return user

    async def update(self, id: UUID, body: UserUpdate) -> User:
        user = await self.get(id)
        updated = await self.users.update(user, body.model_dump(exclude_unset=True))
        await self.db.commit()
        return updated

    async def set_role(self, id: UUID, role: UserRole) -> User:
        user = await self.get(id)
        updated = await self.users.update(user, {"role": role})
        await self.db.commit()
        return updated

    async def delete(self, id: UUID) -> None:
        user = await self.get(id)
        if user.role == UserRole.super_admin:
            raise HTTPException(400, "Super admins cannot be deleted")
        await self.users.delete(user)
        await self.db.commit()
