"""Verifies the orchestrator's crash/restart resumability: a step already marked
succeeded in call_processing_steps must not be re-executed on the next run_pipeline()
call for the same call_id — this is what lets a worker restart mid-pipeline resume
instead of reprocessing the whole call from scratch (a Phase 1 requirement per the
approved plan, not an optional nice-to-have)."""
import uuid
from datetime import datetime, timezone

import pytest

from backend.tests.conftest import requires_postgres


@requires_postgres
@pytest.mark.asyncio
async def test_already_succeeded_step_is_skipped_on_resume(
    db_session, seed_reference_data, monkeypatch, tmp_path
):
    from backend.app.models.calls import Call, CallProcessingStep, CallSource, CallStatus, StepStatus
    from backend.app.models.org import Project, User
    from backend.pipeline import orchestrator as orchestrator_module
    from backend.pipeline import steps as step_functions
    from backend.pipeline.steps_meta import STEP_NAMES

    call_counts: dict[str, int] = {name: 0 for name in STEP_NAMES}

    def _make_fake_step(name: str):
        async def _fake(ctx):
            call_counts[name] += 1
            if name == "transcription":
                ctx.transcript = "hello"
                ctx.detected_language = "en"
            if name == "sentence_speaker_mapping":
                ctx.sentence_speaker_mapping = []  # degenerate: no speech segments
        return _fake

    for name in STEP_NAMES:
        if name in ("persist_results", "qa_evaluation"):
            continue
        monkeypatch.setattr(step_functions, f"step_{name}", _make_fake_step(name))

    # qa_evaluation looks up an active scorecard for the project; none exists here, so
    # run_default_scorecard() is a no-op — no need to fake it separately.
    monkeypatch.setattr(
        orchestrator_module, "cleanup_temp_dir", lambda temp_dir: None
    )

    org = seed_reference_data["org"]
    project = Project(id=uuid.uuid4(), org_id=org.id, name="Idempotency Test Project")
    user = User(
        id=uuid.uuid4(), org_id=org.id, email="idempotency@example.com",
        password_hash="x", full_name="Tester", role_id=seed_reference_data["roles"]["admin"].id,
    )
    db_session.add_all([project, user])
    db_session.commit()

    call = Call(
        id=uuid.uuid4(), org_id=org.id, project_id=project.id, uploaded_by=user.id,
        source=CallSource.upload, original_filename="test.mp3",
        storage_path="test.mp3", checksum="deadbeef" * 8, status=CallStatus.queued,
        uploaded_at=datetime.now(timezone.utc),
    )
    db_session.add(call)
    db_session.commit()

    # Simulate a prior run that already completed "dialogue_detection" before crashing.
    db_session.add(
        CallProcessingStep(
            id=uuid.uuid4(), call_id=call.id, step_name="dialogue_detection", sequence=0,
            status=StepStatus.succeeded, finished_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    # run_pipeline opens its own SessionLocal internally — point it at the same test
    # engine as db_session for this test.
    monkeypatch.setattr(
        orchestrator_module, "SessionLocal", lambda: db_session
    )
    monkeypatch.setattr(orchestrator_module, "get_storage", lambda: _FakeStorage())
    monkeypatch.setattr(orchestrator_module.settings, "pipeline_temp_dir", str(tmp_path))

    await orchestrator_module.run_pipeline(str(call.id))

    assert call_counts["dialogue_detection"] == 0, "already-succeeded step must be skipped"
    assert call_counts["speech_enhancement"] == 1, "not-yet-run steps must still execute"
    assert call.status == "completed"


class _FakeStorage:
    def get_path(self, storage_path: str):
        import pathlib
        return pathlib.Path(storage_path)
