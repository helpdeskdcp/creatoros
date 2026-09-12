"""Creates one OWNER-role demo account for local development.

Usage: python -m scripts.seed_demo_user [email] [password]
Never run this against a production database.
"""
import asyncio
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.modules.users.models import User, UserRole


async def main() -> None:
    settings = get_settings()
    if settings.is_production:
        print("Refusing to seed a demo user in a production environment.")
        sys.exit(1)

    email = sys.argv[1] if len(sys.argv) > 1 else "owner@creatoros.local"
    password = sys.argv[2] if len(sys.argv) > 2 else "ChangeMe123!"

    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing:
            print(f"User {email} already exists (role={existing.role.value}).")
            return

        user = User(
            email=email, hashed_password=hash_password(password), role=UserRole.OWNER, full_name="Demo Owner"
        )
        db.add(user)
        await db.commit()
        print(f"Created OWNER user: {email} / {password}")


if __name__ == "__main__":
    asyncio.run(main())
