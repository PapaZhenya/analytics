import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.dependencies import require_permission
from backend.app.models.org import User
from backend.app.models.qa import QAFinding, QAFindingEvidence, ReviewAction
from backend.app.schemas.findings import (
    ReviewActionHistoryItem,
    ReviewActionRequest,
    ReviewActionResponse,
)

router = APIRouter(prefix="/findings", tags=["findings"])

_REQUIRES_NEW_VERDICT = {"reject", "correct"}


def _get_finding_or_404(db: Session, finding_id: uuid.UUID) -> QAFinding:
    finding = db.get(QAFinding, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    return finding


@router.post("/{finding_id}/review", response_model=ReviewActionResponse)
def review_finding(
    finding_id: uuid.UUID,
    body: ReviewActionRequest,
    user: User = Depends(require_permission("calls.review")),
    db: Session = Depends(get_db),
) -> ReviewActionResponse:
    finding = _get_finding_or_404(db, finding_id)
    now = datetime.now(timezone.utc)
    previous_verdict = finding.current_verdict

    if body.action in _REQUIRES_NEW_VERDICT and body.new_verdict is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"new_verdict is required for action={body.action}"
        )

    if body.action == "confirm":
        finding.reviewed_by = user.id
        finding.reviewed_at = now
        new_verdict_value = finding.current_verdict.value

    elif body.action in _REQUIRES_NEW_VERDICT:
        finding.current_verdict = body.new_verdict
        finding.human_corrected = True
        finding.reviewed_by = user.id
        finding.reviewed_at = now
        finding.notes = body.notes or finding.notes
        new_verdict_value = body.new_verdict

    elif body.action == "add_evidence":
        if body.evidence is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "evidence is required for add_evidence")
        db.add(
            QAFindingEvidence(
                id=uuid.uuid4(),
                finding_id=finding.id,
                utterance_id=body.evidence.utterance_id,
                start_time=body.evidence.start_time,
                end_time=body.evidence.end_time,
                quote_text=body.evidence.quote_text,
                evidence_type=body.evidence.evidence_type,
                added_by=user.id,
            )
        )
        new_verdict_value = finding.current_verdict.value

    elif body.action == "remove_evidence":
        if body.evidence_id is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "evidence_id is required for remove_evidence"
            )
        evidence = db.get(QAFindingEvidence, body.evidence_id)
        if evidence is None or evidence.finding_id != finding.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Evidence not found on this finding")
        db.delete(evidence)
        new_verdict_value = finding.current_verdict.value

    elif body.action == "reopen":
        finding.reviewed_by = None
        finding.reviewed_at = None
        new_verdict_value = finding.current_verdict.value

    else:  # unreachable given the schema's regex, but keeps mypy/readers honest
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unsupported action: {body.action}")

    db.add(
        ReviewAction(
            id=uuid.uuid4(),
            finding_id=finding.id,
            action_type=body.action,
            previous_verdict=previous_verdict,
            new_verdict=new_verdict_value,
            user_id=user.id,
            notes=body.notes,
            created_at=now,
        )
    )
    db.commit()
    db.refresh(finding)

    return ReviewActionResponse(
        finding_id=finding.id,
        current_verdict=finding.current_verdict.value,
        human_corrected=finding.human_corrected,
    )


@router.get("/{finding_id}/history", response_model=list[ReviewActionHistoryItem])
def get_finding_history(
    finding_id: uuid.UUID,
    user: User = Depends(require_permission("calls.view")),
    db: Session = Depends(get_db),
) -> list[ReviewAction]:
    """Full review-action history for a finding — every confirm/reject/correct/reopen
    ever performed, in order, each with who did it and when. Answers 'a manager must be
    able to determine ... whether a person changed it, who changed it and when' for the
    complete history, not just the finding's current state."""
    _get_finding_or_404(db, finding_id)
    return (
        db.query(ReviewAction)
        .filter(ReviewAction.finding_id == finding_id)
        .order_by(ReviewAction.created_at)
        .all()
    )
