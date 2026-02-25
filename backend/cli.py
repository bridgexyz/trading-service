"""CLI tool for admin operations.

Usage:
    python -m backend.cli create-admin
"""

import sys
import getpass

from sqlmodel import Session, select

from backend.database import engine, create_db_and_tables
from backend.models.user import User
from backend.services.auth import hash_password, generate_totp_secret, get_totp_uri


def create_admin():
    """Create an admin user with TOTP setup."""
    create_db_and_tables()

    username = input("Username: ").strip()
    if not username:
        print("Username cannot be empty.")
        sys.exit(1)

    with Session(engine) as session:
        existing = session.exec(select(User).where(User.username == username)).first()
        if existing:
            print(f"User '{username}' already exists.")
            sys.exit(1)

    password = getpass.getpass("Password: ")
    password_confirm = getpass.getpass("Confirm password: ")
    if password != password_confirm:
        print("Passwords do not match.")
        sys.exit(1)

    totp_secret = generate_totp_secret()
    totp_uri = get_totp_uri(totp_secret, username)

    user = User(
        username=username,
        hashed_password=hash_password(password),
        totp_secret=totp_secret,
    )

    with Session(engine) as session:
        session.add(user)
        session.commit()

    print(f"\nAdmin user '{username}' created successfully.")
    print(f"\nTOTP Secret: {totp_secret}")
    print(f"TOTP URI: {totp_uri}")
    print("\nScan the QR code below with your authenticator app:")

    try:
        import qrcode
        qr = qrcode.QRCode(box_size=1, border=1)
        qr.add_data(totp_uri)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except ImportError:
        print("(Install qrcode[pil] to display QR code in terminal)")


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m backend.cli <command>")
        print("Commands: create-admin")
        sys.exit(1)

    command = sys.argv[1]
    if command == "create-admin":
        create_admin()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
