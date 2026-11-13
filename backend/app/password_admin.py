from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from .auth import hash_password
from .database import SessionLocal
from .models import Company, User


def _read_password() -> str:
    while True:
        password = getpass.getpass("Password (12-128 characters): ")
        if len(password) < 12 or len(password) > 128:
            print("Use a password between 12 and 128 characters.")
            continue
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            print("Passwords do not match.")
            continue
        return password


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision password sign-in accounts.")
    parser.add_argument("--check", action="store_true", help="Check whether an active administrator has a password.")
    parser.add_argument("--email", help="Set the password for an existing user account.")
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.check:
            configured = db.scalar(select(User.id).where(User.role == "ADMIN", User.is_active.is_(True), User.password_hash.is_not(None)).limit(1))
            return 0 if configured else 1

        admins = db.scalars(select(User).where(User.role == "ADMIN", User.is_active.is_(True)).order_by(User.created_at)).all()
        default_email = admins[0].email if admins and not admins[0].email.endswith("@example.test") else ""
        email = args.email or input(f"Admin email [{default_email}]: ").strip()
        if not email and admins:
            email = admins[0].email
        email = email.strip().lower()
        if "@" not in email:
            print("Enter a valid email address.", file=sys.stderr)
            return 2

        user = db.scalar(select(User).where(User.email == email))
        if args.email and not user:
            print("That account does not exist. Create it from the Users page first.", file=sys.stderr)
            return 2
        if user and (not user.is_active or user.role != "ADMIN"):
            print("The account must be an active administrator.", file=sys.stderr)
            return 2
        if not user:
            company = db.scalar(select(Company).order_by(Company.created_at))
            if not company:
                print("Create a company record before configuring the administrator account.", file=sys.stderr)
                return 2
            name = input("Administrator name: ").strip()
            if len(name) < 2:
                print("Enter an administrator name with at least 2 characters.", file=sys.stderr)
                return 2
            user = User(company_id=company.id, full_name=name, email=email, role="ADMIN", is_active=True)
            db.add(user)

        user.password_hash = hash_password(_read_password())
        db.commit()
        print(f"Password sign-in is ready for {user.email}. The password is not displayed.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
