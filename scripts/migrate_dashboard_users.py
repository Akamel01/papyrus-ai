#!/usr/bin/env python3
"""
Migrate Dashboard Users to Unified Auth Service

This script migrates existing dashboard users from the JSON file
(data/dashboard_users.json) to the Auth Service SQLite database (data/auth.db).

Migration mapping:
- username -> email: {username}@dashboard.local
- hashed_password: preserved (both use bcrypt)
- role -> dashboard_role: admin/operator/viewer
- role (auth service): admin if dashboard admin, otherwise user

Usage:
    python scripts/migrate_dashboard_users.py [--dry-run]

Options:
    --dry-run    Show what would be migrated without making changes
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("migrate_dashboard_users")

# File paths
DASHBOARD_USERS_FILE = Path("data/dashboard_users.json")
AUTH_DB_PATH = "sqlite:///./data/auth.db"


def load_dashboard_users() -> dict:
    """Load existing dashboard users from JSON file."""
    if not DASHBOARD_USERS_FILE.exists():
        logger.warning(f"Dashboard users file not found: {DASHBOARD_USERS_FILE}")
        return {}

    with open(DASHBOARD_USERS_FILE, "r") as f:
        return json.load(f)


def migrate_users(dry_run: bool = False):
    """Migrate dashboard users to Auth Service database."""
    from services.auth.models import User, get_engine, create_tables, get_session_factory

    # Load dashboard users
    dashboard_users = load_dashboard_users()
    if not dashboard_users:
        logger.info("No dashboard users to migrate")
        return 0

    logger.info(f"Found {len(dashboard_users)} dashboard users to migrate")

    if dry_run:
        logger.info("DRY RUN - No changes will be made")
        for username, data in dashboard_users.items():
            email = f"{username}@dashboard.local"
            dashboard_role = data.get("role", "viewer")
            auth_role = "admin" if dashboard_role == "admin" else "user"
            logger.info(f"  Would migrate: {username} -> {email} (dashboard_role={dashboard_role}, auth_role={auth_role})")
        return len(dashboard_users)

    # Initialize database
    engine = get_engine(AUTH_DB_PATH)
    create_tables(engine)
    SessionFactory = get_session_factory(engine)
    db = SessionFactory()

    migrated = 0
    skipped = 0
    errors = 0

    try:
        for username, data in dashboard_users.items():
            email = f"{username}@dashboard.local"
            dashboard_role = data.get("role", "viewer")
            auth_role = "admin" if dashboard_role == "admin" else "user"
            hashed_password = data.get("hashed_password", "")

            # Check if user already exists
            existing = db.query(User).filter(User.email == email).first()
            if existing:
                logger.info(f"  SKIP: {username} already exists as {email}")
                skipped += 1
                continue

            try:
                # Create new user in Auth Service
                new_user = User(
                    email=email,
                    password_hash=hashed_password,
                    display_name=username,
                    role=auth_role,
                    dashboard_role=dashboard_role,
                    created_at=datetime.utcnow(),
                    is_active="true"
                )
                db.add(new_user)
                db.commit()

                logger.info(f"  MIGRATED: {username} -> {email} (dashboard_role={dashboard_role})")
                migrated += 1

            except Exception as e:
                logger.error(f"  ERROR migrating {username}: {e}")
                db.rollback()
                errors += 1

    finally:
        db.close()

    logger.info(f"Migration complete: {migrated} migrated, {skipped} skipped, {errors} errors")
    return migrated


def main():
    parser = argparse.ArgumentParser(description="Migrate Dashboard users to Auth Service")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be migrated")
    args = parser.parse_args()

    try:
        count = migrate_users(dry_run=args.dry_run)
        if count > 0:
            logger.info(f"Successfully processed {count} users")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
