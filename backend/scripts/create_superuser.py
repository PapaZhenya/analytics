"""Bootstrap the first Super Admin account.

Deliberately a separate, explicit step rather than a seeded migration row — a fixed
default admin/password baked into a migration is a well-known vulnerability class.

Usage:
    python -m backend.scripts.create_superuser --email admin@example.com --password '...' --name "Admin"
"""
import argparse
import sys
import uuid

sys.path.insert(0, ".")

from backend.app.db.session import SessionLocal  # noqa: E402
from backend.app.models.org import Organization, Role, User  # noqa: E402
from backend.app.security import hash_password  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", default="Super Admin")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        org = db.query(Organization).first()
        if org is None:
            print("No organization found — run `alembic upgrade head` first.", file=sys.stderr)
            sys.exit(1)

        role = db.query(Role).filter(Role.code == "super_admin").first()
        if role is None:
            print("super_admin role not found — run `alembic upgrade head` first.", file=sys.stderr)
            sys.exit(1)

        existing = db.query(User).filter(User.email == args.email).first()
        if existing is not None:
            print(f"User {args.email} already exists.", file=sys.stderr)
            sys.exit(1)

        user = User(
            id=uuid.uuid4(),
            org_id=org.id,
            email=args.email,
            password_hash=hash_password(args.password),
            full_name=args.name,
            role_id=role.id,
            is_active=True,
        )
        db.add(user)
        db.commit()
        print(f"Created super_admin user: {args.email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
