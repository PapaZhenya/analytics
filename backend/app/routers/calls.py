"""Call lifecycle: upload, list, detail, processing status, reprocess/cancel.

Audio streaming lives in routers/audio.py; transcript/speaker-role corrections live in
routers/transcripts.py — split out to keep each router focused on one concern rather
than one large file mixing call CRUD, storage-serving, and editorial actions.
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.dependencies import get_call_or_404, require_permission
from backend.app.models.calls import Call, CallProcessingStep, CallStatus, CallTag, Utterance
from backend.app.models.collab import Comment
from backend.app.models.org import User
from backend.app.models.qa import QAEvaluation
from backend.app.schemas.calls import (
    CallDetailResponse,
    CallListItem,
    CallListResponse,
    CallStatusResponse,
    CommentOut,
    EvidenceOut,
    FindingOut,
    ProcessingStepOut,
    QAEvaluationOut,
    SpeakerOut,
    UtteranceOut,
)
from backend.app.rate_limit import limiter
from backend.app.services.call_service import (
    DuplicateUploadError,
    FileTooLargeError,
    UnsupportedFileTypeError,
    cancel_call,
    create_call_from_upload,
    reprocess_call,
)
from backend.pipeline.steps_meta import STEP_NAMES

router = APIRouter(prefix="/calls", tags=["calls"])


@router.post("", response_model=list[CallListItem], status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
def upload_calls(
    request: Request,
    project_id: uuid.UUID,
    agent_id: uuid.UUID | None = None,
    files: list[UploadFile] = ...,
    user: User = Depends(require_permission("calls.upload")),
    db: Session = Depends(get_db),
) -> list[Call]:
    created: list[Call] = []
    errors: list[str] = []

    for upload in files:
        try:
            call = create_call_from_upload(db, user, project_id, agent_id, upload)
            created.append(call)
        except DuplicateUploadError as exc:
            errors.append(f"{upload.filename}: duplicate of existing call {exc.existing_call.id}")
        except UnsupportedFileTypeError as exc:
            errors.append(f"{upload.filename}: {exc}")
        except FileTooLargeError as exc:
            errors.append(f"{upload.filename}: {exc}")

    if not created and errors:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "; ".join(errors))

    return created


@router.get("", response_model=CallListResponse)
def list_calls(
    project_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    status_filter: CallStatus | None = Query(None, alias="status"),
    language: str | None = None,
    source: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    user: User = Depends(require_permission("calls.view")),
    db: Session = Depends(get_db),
) -> CallListResponse:
    stmt = select(Call).where(Call.org_id == user.org_id)

    if project_id is not None:
        stmt = stmt.where(Call.project_id == project_id)
    if agent_id is not None:
        stmt = stmt.where(Call.agent_id == agent_id)
    if status_filter is not None:
        stmt = stmt.where(Call.status == status_filter)
    if language is not None:
        stmt = stmt.where(Call.detected_language == language)
    if source is not None:
        stmt = stmt.where(Call.source == source)
    if date_from is not None:
        stmt = stmt.where(Call.uploaded_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Call.uploaded_at <= date_to)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    stmt = stmt.order_by(Call.uploaded_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = db.execute(stmt).scalars().all()

    return CallListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{call_id}", response_model=CallDetailResponse)
def get_call_detail(
    call_id: uuid.UUID,
    user: User = Depends(require_permission("calls.view")),
    db: Session = Depends(get_db),
) -> CallDetailResponse:
    call = get_call_or_404(db, call_id, user.org_id)

    speakers_out = [
        SpeakerOut(
            id=s.id, diarization_label=s.diarization_label, role_code=s.role.code,
            display_name=s.display_name,
            role_confidence=float(s.role_confidence) if s.role_confidence is not None else None,
            role_manually_corrected=s.role_corrected_by is not None,
            role_corrected_by=s.role_corrected_by,
            role_corrected_at=s.role_corrected_at,
        )
        for s in call.speakers
    ]

    utterances_out = []
    utterance_rows = (
        db.query(Utterance).filter(Utterance.call_id == call.id).order_by(Utterance.sequence).all()
    )
    for u in utterance_rows:
        latest_correction = u.corrections[-1] if u.corrections else None
        utterances_out.append(
            UtteranceOut(
                id=u.id,
                speaker_id=u.speaker_id,
                sequence=u.sequence,
                start_time=float(u.start_time),
                end_time=float(u.end_time),
                content=(latest_correction.corrected_content if latest_correction and latest_correction.corrected_content else u.original_content),
                original_content=u.original_content,
                is_corrected=latest_correction is not None,
                sentiment=u.sentiment,
                is_profane=u.is_profane,
            )
        )

    evaluations = db.query(QAEvaluation).filter(QAEvaluation.call_id == call.id).all()
    evaluations_out = []
    for ev in evaluations:
        findings_out = []
        for f in ev.findings:
            findings_out.append(
                FindingOut(
                    id=f.id,
                    criterion_id=f.criterion_id,
                    criterion_code=f.criterion.code,
                    criterion_text=f.criterion.text,
                    rule_type=f.criterion.rule_type.value,
                    ai_verdict=f.ai_verdict.value,
                    ai_confidence=float(f.ai_confidence) if f.ai_confidence is not None else None,
                    ai_explanation=f.ai_explanation,
                    engine_version=f.engine_version,
                    current_verdict=f.current_verdict.value,
                    human_corrected=f.human_corrected,
                    reviewed_by=f.reviewed_by,
                    reviewed_at=f.reviewed_at,
                    notes=f.notes,
                    evidence=[
                        EvidenceOut(
                            id=e.id, utterance_id=e.utterance_id, start_time=float(e.start_time),
                            end_time=float(e.end_time), quote_text=e.quote_text,
                            evidence_type=e.evidence_type.value, added_by=e.added_by,
                        )
                        for e in f.evidence
                    ],
                )
            )
        evaluations_out.append(
            QAEvaluationOut(
                id=ev.id, scorecard_id=ev.scorecard_id,
                scorecard_version=ev.scorecard.version,
                scorecard_name=ev.scorecard.name,
                overall_score=float(ev.overall_score) if ev.overall_score is not None else None,
                max_score=float(ev.max_score) if ev.max_score is not None else None,
                status=ev.status.value, findings=findings_out,
            )
        )

    comments = (
        db.query(Comment).filter(Comment.call_id == call.id).order_by(Comment.created_at).all()
    )
    tags = [t.tag for t in db.query(CallTag).filter(CallTag.call_id == call.id).all()]

    return CallDetailResponse(
        id=call.id,
        original_filename=call.original_filename,
        status=call.status,
        source=call.source,
        detected_language=call.detected_language,
        duration_seconds=float(call.duration_seconds) if call.duration_seconds is not None else None,
        uploaded_at=call.uploaded_at,
        processed_at=call.processed_at,
        checksum=call.checksum,
        uploaded_by=call.uploaded_by,
        channel_count=call.channel_count,
        is_separate_channel_recording=call.is_separate_channel_recording,
        model_versions=call.model_versions,
        speakers=speakers_out,
        utterances=utterances_out,
        evaluations=evaluations_out,
        comments=[CommentOut.model_validate(c) for c in comments],
        tags=tags,
    )


@router.get("/{call_id}/status", response_model=CallStatusResponse)
def get_call_status(
    call_id: uuid.UUID,
    user: User = Depends(require_permission("calls.view")),
    db: Session = Depends(get_db),
) -> CallStatusResponse:
    call = get_call_or_404(db, call_id, user.org_id)
    steps = (
        db.query(CallProcessingStep)
        .filter(CallProcessingStep.call_id == call.id)
        .order_by(CallProcessingStep.sequence)
        .all()
    )
    succeeded = sum(1 for s in steps if s.status.value == "succeeded")
    percent = int(100 * succeeded / len(STEP_NAMES)) if call.status != CallStatus.completed else 100

    return CallStatusResponse(
        call_id=call.id,
        status=call.status,
        steps=[
            ProcessingStepOut(
                step_name=s.step_name, sequence=s.sequence, status=s.status.value,
                started_at=s.started_at, finished_at=s.finished_at, error_message=s.error_message,
            )
            for s in steps
        ],
        percent_complete=percent,
    )


@router.post("/{call_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
def reprocess(
    call_id: uuid.UUID,
    user: User = Depends(require_permission("calls.reprocess")),
    db: Session = Depends(get_db),
) -> dict:
    call = get_call_or_404(db, call_id, user.org_id)
    reprocess_call(db, call, user)
    return {"status": "queued"}


@router.post("/{call_id}/cancel", status_code=status.HTTP_200_OK)
def cancel(
    call_id: uuid.UUID,
    user: User = Depends(require_permission("calls.cancel")),
    db: Session = Depends(get_db),
) -> dict:
    call = get_call_or_404(db, call_id, user.org_id)
    cancelled = cancel_call(db, call, user)
    if not cancelled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Call cannot be cancelled once processing has started (technically unsafe to interrupt).",
        )
    return {"status": "cancelled"}
