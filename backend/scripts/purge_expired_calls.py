"""Enforces Call.retention_expires_at (section 9: "retention and deletion policies").

Deliberately a manual/cron-invoked script rather than an automatic Celery Beat
schedule for Phase 1 — deleting audio recordings is exactly the kind of action that
should not silently start happening on its own the moment `DEFAULT_RETENTION_DAYS` gets
set in an env file; an operator should be able to dry-run this and see what it *would*
delete before it's wired into an unattended schedule (a natural Phase 2 addition once
the retention policy itself has been validated in a given deployment).

Only the **audio file** is deleted — the Call row and everything derived from it
(utterances, QA findings, evidence, review history) are kept. This is deliberate, not
an oversight: section 8 requires historical QA reports stay explainable indefinitely,
which is a different lifecycle than "how long do we keep the raw recording" — deleting
the evaluation history along with the audio would silently make past reports
unexplainable, which is the one thing this whole feature area must not do.

Usage:
    python -m backend.scripts.purge_expired_calls --dry-run
    python -m backend.scripts.purge_expired_calls
"""
import argparse
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, ".")

from backend.app.db.session import SessionLocal  # noqa: E402
from backend.app.models.calls import Call  # noqa: E402
from backend.app.models.org import AuditLog  # noqa: E402
from backend.pipeline.storage import get_storage  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true", help="List what would be purged without deleting anything"
    )
    args = parser.parse_args()

    db = SessionLocal()
    storage = get_storage()
    now = datetime.now(timezone.utc)

    try:
        expired = (
            db.query(Call)
            .filter(Call.retention_expires_at.isnot(None), Call.retention_expires_at < now, Call.deleted_at.is_(None))
            .all()
        )

        if not expired:
            print("No calls past their retention period.")
            return

        for call in expired:
            print(f"{'[dry-run] ' if args.dry_run else ''}Purging audio for call {call.id} "
                  f"({call.original_filename}, retained past {call.retention_expires_at})")
            if args.dry_run:
                continue

            storage.delete(call.storage_path)
            call.deleted_at = now
            db.add(
                AuditLog(
                    id=uuid.uuid4(),
                    org_id=call.org_id,
                    user_id=None,  # system action, not a specific user
                    action="call_audio_purged",
                    entity_type="call",
                    entity_id=call.id,
                    audit_metadata={"retention_expires_at": call.retention_expires_at.isoformat()},
                    created_at=now,
                )
            )

        if not args.dry_run:
            db.commit()
            print(f"Purged audio for {len(expired)} call(s). QA/transcript history was NOT deleted.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
