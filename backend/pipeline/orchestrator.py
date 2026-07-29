"""Replaces main.py's `async def main(audio_file_path)`. Same 18 (broken-out-to-21)
steps, same src/ classes, but:
  - operates on a call_id + the call's permanently stored recording, not a watch-folder path
  - writes call_processing_steps idempotently and checkpoints intermediate results to
    disk, so a worker crash/restart resumes from the last succeeded step instead of
    reprocessing the whole call from scratch
  - never deletes the original audio (only the .temp/ working directory is cleaned up)
  - persists via SQLAlchemy instead of src/db/manager.py::Database
"""
import json
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.db.session import SessionLocal
from backend.app.models.calls import (
    AcousticMetrics,
    AudioVariant,
    Call,
    CallProcessingStep,
    CallStatus,
    CallSummary,
    Sentiment,
    Speaker,
    SpeakerRole,
    StepStatus,
    Utterance,
)
from backend.pipeline import steps as step_functions
from backend.pipeline.context import PipelineContext
from backend.pipeline.steps_meta import STEP_NAMES, STEP_SEQUENCE, STEP_TO_CALL_STATUS
from backend.pipeline.storage import get_storage
from backend.utils.cleanup import cleanup_temp_dir

settings = get_settings()

# Steps handled specially (not a straight src/ class wrapper) — see below.
_SPECIAL_STEPS = {"qa_evaluation", "persist_results"}

# Maps the legacy Customer/CSR labels that LLMResultHandler (unmodified) still produces
# onto our extensible speaker_roles taxonomy.
_LEGACY_ROLE_TO_CODE = {"Customer": "client", "CSR": "agent"}

_JSON_CHECKPOINT_FIELDS = [
    "channel_count",
    "is_separate_channel_recording",
    "model_versions",
    "role_assignment_used_fallback",
    "enhanced_audio_path",
    "vocal_audio_path",
    "mono_audio_path",
    "transcript",
    "detected_language",
    "word_timestamps",
    "rttm_path",
    "speaker_timestamps",
    "word_speaker_mapping",
    "sentence_speaker_mapping",
    "speaker_roles_raw",
    "sentiment_results",
    "profanity_results",
    "summary_result",
    "conflict_result",
    "topic_result",
    "silence_threshold",
    "interruption_count",
    "agent_talk_ratio",
]


def _checkpoint_path(temp_dir: str) -> str:
    return os.path.join(temp_dir, "checkpoint.json")


def _save_checkpoint(ctx: PipelineContext) -> None:
    data = {field: getattr(ctx, field) for field in _JSON_CHECKPOINT_FIELDS}
    if ctx.acoustic_properties is not None:
        data["acoustic_properties"] = list(ctx.acoustic_properties)
    os.makedirs(ctx.temp_dir, exist_ok=True)
    with open(_checkpoint_path(ctx.temp_dir), "w", encoding="utf-8") as f:
        json.dump(data, f)


def _load_checkpoint(ctx: PipelineContext) -> None:
    path = _checkpoint_path(ctx.temp_dir)
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for field in _JSON_CHECKPOINT_FIELDS:
        if field in data:
            setattr(ctx, field, data[field])
    if "acoustic_properties" in data:
        ctx.acoustic_properties = tuple(data["acoustic_properties"])


def _get_step_row(db: Session, call_id: uuid.UUID, step_name: str) -> CallProcessingStep:
    row = (
        db.query(CallProcessingStep)
        .filter(CallProcessingStep.call_id == call_id, CallProcessingStep.step_name == step_name)
        .one_or_none()
    )
    if row is None:
        row = CallProcessingStep(
            id=uuid.uuid4(),
            call_id=call_id,
            step_name=step_name,
            sequence=STEP_SEQUENCE[step_name],
            status=StepStatus.pending,
        )
        db.add(row)
        db.commit()
    return row


def _step_already_succeeded(db: Session, call_id: uuid.UUID, step_name: str) -> bool:
    row = _get_step_row(db, call_id, step_name)
    return row.status == StepStatus.succeeded


def _mark_running(db: Session, call: Call, step_name: str) -> None:
    row = _get_step_row(db, call.id, step_name)
    row.status = StepStatus.running
    row.started_at = datetime.now(timezone.utc)
    row.error_message = None
    call.status = STEP_TO_CALL_STATUS[step_name]
    db.commit()


def _mark_succeeded(db: Session, call_id: uuid.UUID, step_name: str) -> None:
    row = _get_step_row(db, call_id, step_name)
    row.status = StepStatus.succeeded
    row.finished_at = datetime.now(timezone.utc)
    db.commit()


def _mark_failed(db: Session, call_id: uuid.UUID, step_name: str, error: str) -> None:
    row = _get_step_row(db, call_id, step_name)
    row.status = StepStatus.failed
    row.finished_at = datetime.now(timezone.utc)
    row.error_message = error[:4000]
    db.commit()


async def _run_wrapped_step(ctx: PipelineContext, step_name: str) -> None:
    fn = getattr(step_functions, f"step_{step_name}")
    _mark_running(ctx.db, ctx.call, step_name)
    try:
        await fn(ctx)
    except Exception as exc:
        _mark_failed(ctx.db, ctx.call.id, step_name, f"{type(exc).__name__}: {exc}")
        raise
    else:
        _save_checkpoint(ctx)
        _mark_succeeded(ctx.db, ctx.call.id, step_name)


def _persist_results(ctx: PipelineContext) -> None:
    db = ctx.db
    call = ctx.call
    ssm = ctx.sentence_speaker_mapping

    # Idempotent re-run safety: if persist_results partially ran before a crash, wipe any
    # partial rows for this call before re-inserting (delete-then-reinsert-in-transaction,
    # per the plan's idempotency design for per-call-many tables).
    db.query(Utterance).filter(
        Utterance.speaker_id.in_(
            db.query(Speaker.id).filter(Speaker.call_id == call.id)
        )
    ).delete(synchronize_session=False)
    db.query(Speaker).filter(Speaker.call_id == call.id).delete(synchronize_session=False)
    db.commit()

    role_rows = {r.code: r for r in db.query(SpeakerRole).all()}
    speaker_by_label: dict[str, Speaker] = {}

    # Heuristic confidence tier (NOT a calibrated probability — see
    # Speaker.role_confidence's docstring): high when the LLM classification validated
    # cleanly, low when it fell back to "first speaker = CSR". Deliberately not 1.0/0.0
    # so nothing downstream mistakes either tier for certainty.
    role_confidence = 0.3 if ctx.role_assignment_used_fallback else 0.85

    for item in ssm:
        legacy_label = item["speaker"]  # "Customer" / "CSR" (unmodified LLMResultHandler output)
        role_code = _LEGACY_ROLE_TO_CODE.get(legacy_label, "unknown")
        if legacy_label not in speaker_by_label:
            speaker = Speaker(
                id=uuid.uuid4(),
                call_id=call.id,
                diarization_label=legacy_label,
                role_id=role_rows[role_code].id,
                display_name=legacy_label,
                role_confidence=role_confidence,
            )
            db.add(speaker)
            db.flush()
            speaker_by_label[legacy_label] = speaker

    sentiments = {s["index"]: s["sentiment"] for s in ctx.sentiment_results.get("sentiments", [])} \
        if ctx.sentiment_results else {}
    profanity = {p["index"]: p["profane"] for p in ctx.profanity_results.get("profanity", [])} \
        if ctx.profanity_results else {}

    for idx, item in enumerate(ssm):
        speaker = speaker_by_label[item["speaker"]]
        sentiment_value = sentiments.get(idx)
        db.add(
            Utterance(
                id=uuid.uuid4(),
                call_id=call.id,
                speaker_id=speaker.id,
                sequence=idx,
                start_time=item["start_time"],
                end_time=item["end_time"],
                original_content=item["text"],
                sentiment=Sentiment(sentiment_value) if sentiment_value in Sentiment.__members__ else None,
                is_profane=bool(profanity.get(idx, False)),
            )
        )

    if ctx.acoustic_properties is not None:
        (
            _name, _ext, _path, rate, min_freq, max_freq, _bit_depth, _channels,
            _duration, rms_loudness, features,
        ) = ctx.acoustic_properties
        db.query(AcousticMetrics).filter(AcousticMetrics.call_id == call.id).delete(
            synchronize_session=False
        )
        db.add(
            AcousticMetrics(
                id=uuid.uuid4(),
                call_id=call.id,
                source_audio_variant=AudioVariant.original,
                rms_loudness=rms_loudness,
                zero_crossing_rate=features.get("ZeroCrossingRate"),
                spectral_centroid=features.get("SpectralCentroid"),
                eq_20_250=features.get("EQ_20_250_Hz"),
                eq_250_2000=features.get("EQ_250_2000_Hz"),
                eq_2000_6000=features.get("EQ_2000_6000_Hz"),
                eq_6000_20000=features.get("EQ_6000_20000_Hz"),
                **{f"mfcc_{i}": features.get(f"MFCC_{i}") for i in range(1, 14)},
                silence_ratio=ctx.silence_threshold,
                interruption_count=ctx.interruption_count,
                agent_talk_ratio=ctx.agent_talk_ratio,
            )
        )

    db.query(CallSummary).filter(CallSummary.call_id == call.id).delete(synchronize_session=False)
    db.add(
        CallSummary(
            id=uuid.uuid4(),
            call_id=call.id,
            summary_text=(ctx.summary_result or {}).get("summary"),
            conflict_detected=bool((ctx.conflict_result or {}).get("conflict", False)),
            conflict_details=None,
            topics={"topic": (ctx.topic_result or {}).get("topic", "Unknown")},
        )
    )
    db.commit()


async def _run_qa_evaluation(ctx: PipelineContext) -> None:
    from backend.pipeline.qa_engine.orchestrator import run_default_scorecard

    await run_default_scorecard(ctx)


async def run_pipeline(call_id: str) -> None:
    db = SessionLocal()
    try:
        call = db.get(Call, uuid.UUID(call_id))
        if call is None:
            raise ValueError(f"Call {call_id} not found")

        storage = get_storage()
        temp_dir = os.path.join(settings.pipeline_temp_dir, call_id)
        ctx = PipelineContext(
            db=db,
            call=call,
            call_id=call_id,
            temp_dir=temp_dir,
            original_audio_path=str(storage.get_path(call.storage_path)),
        )
        _load_checkpoint(ctx)

        for step_name in STEP_NAMES:
            if step_name in _SPECIAL_STEPS:
                continue
            if _step_already_succeeded(db, call.id, step_name):
                continue
            await _run_wrapped_step(ctx, step_name)

        if not _step_already_succeeded(db, call.id, "persist_results"):
            _mark_running(db, call, "persist_results")
            try:
                _persist_results(ctx)
            except Exception as exc:
                _mark_failed(db, call.id, "persist_results", f"{type(exc).__name__}: {exc}")
                raise
            else:
                _mark_succeeded(db, call.id, "persist_results")

        # Runs after persist_results (not before) so qa_finding_evidence can reference
        # real, already-committed utterance_id rows rather than in-memory-only sequence
        # indices.
        if not _step_already_succeeded(db, call.id, "qa_evaluation"):
            _mark_running(db, call, "qa_evaluation")
            try:
                await _run_qa_evaluation(ctx)
            except Exception as exc:
                _mark_failed(db, call.id, "qa_evaluation", f"{type(exc).__name__}: {exc}")
                raise
            else:
                _mark_succeeded(db, call.id, "qa_evaluation")

        call.status = CallStatus.completed
        call.processed_at = datetime.now(timezone.utc)
        db.commit()

        # Only the ephemeral working directory is removed — the permanently stored
        # recording (ctx.original_audio_path, under AudioStorage) is never touched.
        cleanup_temp_dir(temp_dir)
    finally:
        db.close()
