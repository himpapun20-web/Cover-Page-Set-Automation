from __future__ import annotations

import os

from sqlalchemy import select

from .auth import hash_password
from .database import SessionLocal
from .models import User
from .seed import seed_demo_data


def main() -> None:
    if os.getenv("CCTV_AUTH_MODE", "").strip().lower() != "password":
        raise RuntimeError("The Render demo must use password authentication.")

    secret = os.getenv("CCTV_AUTH_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("CCTV_AUTH_SECRET must contain at least 32 characters.")

    email = os.getenv("DEMO_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("DEMO_ADMIN_PASSWORD", "")
    if "@" not in email:
        raise RuntimeError("Set DEMO_ADMIN_EMAIL to the demo administrator's email address.")
    if len(password) < 12 or len(password) > 128:
        raise RuntimeError("DEMO_ADMIN_PASSWORD must be between 12 and 128 characters.")

    with SessionLocal() as db:
        seed_demo_data(db, admin_email=email)
        admin = db.scalar(select(User).where(User.email == email))
        if not admin or not admin.is_active or admin.role != "ADMIN":
            raise RuntimeError("The synthetic demo administrator could not be initialized.")

        if admin.password_hash is None:
            admin.password_hash = hash_password(password)
        db.commit()


if __name__ == "__main__":
    main()
