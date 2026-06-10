from sqlalchemy import select
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole
async def seed_super_admin():
    async with SessionLocal() as db:
        user=(await db.execute(select(User).where(User.email==settings.super_admin_email))).scalar_one_or_none()
        if not user:
            db.add(User(email=settings.super_admin_email,full_name="Super Admin",hashed_password=hash_password(settings.super_admin_password),role=UserRole.super_admin,is_active=True)); await db.commit()
