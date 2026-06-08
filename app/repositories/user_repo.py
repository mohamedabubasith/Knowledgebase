from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import User, UserRole


class UserRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, id: UUID) -> User | None:
        return await self.db.get(User, id)

    async def get_by_email(self, email: str) -> User | None:
        return await self.db.scalar(select(User).where(User.email == email))

    async def list_all(self) -> list[User]:
        return list((await self.db.scalars(select(User).order_by(User.created_at.desc()))).all())

    async def create(self, email: str, hashed_password: str, full_name: str, role: UserRole) -> User:
        user = User(email=email, hashed_password=hashed_password, full_name=full_name, role=role)
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def update(self, user: User, fields: dict) -> User:
        for k, v in fields.items():
            setattr(user, k, v)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def delete(self, user: User) -> None:
        await self.db.delete(user)
        await self.db.flush()
