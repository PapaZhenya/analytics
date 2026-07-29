"""Correcting AI-derived output — split out from calls.py: this is an editorial/QA
concern (a reviewer overriding transcript text or a speaker's role), distinct from
call-lifecycle CRUD."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.dependencies import require_permission
from backend.app.models.calls import Speaker, SpeakerRole, Utterance, UtteranceCorrection
from backend.app.models.org import AuditLog, User
from backend.app.schemas.calls import (
    SpeakerRoleCorrectionRequest,
    SpeakerRoleCorrectionResponse,
    UtteranceCorrectionRequest,
    UtteranceCorrectionResponse,
)

router = APIRouter(prefix="/calls", tags=["transcripts"])


@router.post("/{call_id}/utterances/{utterance_id}/correct", response_model=UtteranceCorrectionResponse)
def correct_utterance(
    call_id: uuid.UUID,
    utterance_id: uuid.UUID,
    body: UtteranceCorrectionRequest,
    user: User = Depends(require_permission("transcripts.correct")),
    db: Session = Depends(get_db),
) -> UtteranceCorrectionResponse:
    utterance = db.get(Utterance, utterance_id)
    if utterance is None or utterance.call_id != call_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utterance not found")

    if body.corrected_content is None and body.corrected_speaker_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Provide corrected_content and/or corrected_speaker_id"
        )

    # Append-only revision — the original ASR output (utterance.original_content) is
    # never mutated, satisfying "preserving the original machine transcript".
    correction = UtteranceCorrection(
        id=uuid.uuid4(),
        utterance_id=utterance.id,
        corrected_content=body.corrected_content,
        corrected_speaker_id=body.corrected_speaker_id,
        corrected_by=user.id,
        reason=body.reason,
        created_at=datetime.now(timezone.utc),
    )
    db.add(correction)
    db.commit()

    return UtteranceCorrectionResponse(
        utterance_id=utterance.id,
        content=body.corrected_content or utterance.original_content,
        speaker_id=body.corrected_speaker_id or utterance.speaker_id,
        is_corrected=True,
    )


@router.post("/{call_id}/speakers/{speaker_id}/correct-role", response_model=SpeakerRoleCorrectionResponse)
def correct_speaker_role(
    call_id: uuid.UUID,
    speaker_id: uuid.UUID,
    body: SpeakerRoleCorrectionRequest,
    user: User = Depends(require_permission("transcripts.correct")),
    db: Session = Depends(get_db),
) -> SpeakerRoleCorrectionResponse:
    """Directly corrects which role a whole speaker was assigned (Agent vs Client),
    rather than requiring a reviewer to fix every individual utterance's speaker
    assignment by hand — for exactly the case where diarization correctly separated the
    two voices but role classification (Speaker.role_confidence — see that field's
    docstring) got the Agent/Client label backwards."""
    speaker = db.get(Speaker, speaker_id)
    if speaker is None or speaker.call_id != call_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Speaker not found")

    new_role = db.query(SpeakerRole).filter(SpeakerRole.code == body.new_role_code).one_or_none()
    if new_role is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown role code: {body.new_role_code!r}")

    old_role_code = speaker.role.code
    speaker.role_id = new_role.id
    speaker.role_confidence = 1.0  # human-confirmed, not a heuristic tier anymore
    speaker.role_corrected_by = user.id
    speaker.role_corrected_at = datetime.now(timezone.utc)

    db.add(
        AuditLog(
            id=uuid.uuid4(),
            org_id=user.org_id,
            user_id=user.id,
            action="speaker_role_corrected",
            entity_type="speaker",
            entity_id=speaker.id,
            audit_metadata={
                "call_id": str(call_id),
                "old_role": old_role_code,
                "new_role": body.new_role_code,
                "reason": body.reason,
            },
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    return SpeakerRoleCorrectionResponse(
        speaker_id=speaker.id, role_code=body.new_role_code, role_confidence=1.0
    )
