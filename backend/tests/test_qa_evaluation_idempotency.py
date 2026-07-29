"""A retried qa_evaluation pipeline step must not leave an orphaned partial
QAEvaluation behind, nor ever touch one a human has already reviewed — see
backend/pipeline/qa_engine/orchestrator.py::_clear_unreviewed_evaluation."""
import uuid
from datetime import datetime, timezone

import pytest

from backend.tests.conftest import requires_postgres


@requires_postgres
@pytest.mark.asyncio
async def test_retry_replaces_unreviewed_evaluation_not_duplicates_it(
    db_session, seed_reference_data
):
    from backend.app.models.calls import Call, CallSource, CallStatus
    from backend.app.models.org import Project, User
    from backend.app.models.qa import (
        EvaluationStatus,
        RuleType,
        Scorecard,
        ScorecardCriterion,
        ScorecardSection,
        ScoringLogic,
        SpeakerScope,
        EvaluationMode,
        QAEvaluation,
    )
    from backend.pipeline.qa_engine.orchestrator import run_scorecard

    org = seed_reference_data["org"]
    project = Project(id=uuid.uuid4(), org_id=org.id, name="Idempotent QA Test")
    user = User(
        id=uuid.uuid4(), org_id=org.id, email="qa-idem@example.com",
        password_hash="x", full_name="Tester", role_id=seed_reference_data["roles"]["admin"].id,
    )
    db_session.add_all([project, user])
    db_session.commit()

    call = Call(
        id=uuid.uuid4(), org_id=org.id, project_id=project.id, uploaded_by=user.id,
        source=CallSource.upload, original_filename="t.mp3", storage_path="t.mp3",
        checksum="a" * 64, status=CallStatus.analyzing, uploaded_at=datetime.now(timezone.utc),
    )
    db_session.add(call)
    db_session.commit()

    scorecard = Scorecard(
        id=uuid.uuid4(), group_id=uuid.uuid4(), version=1, name="Test Scorecard",
        project_id=project.id, is_active=True, created_by=user.id,
    )
    db_session.add(scorecard)
    db_session.flush()
    section = ScorecardSection(id=uuid.uuid4(), scorecard_id=scorecard.id, name="Section", order_index=0, weight=1)
    db_session.add(section)
    db_session.flush()
    criterion = ScorecardCriterion(
        id=uuid.uuid4(), section_id=section.id, code="c1", text="Test criterion",
        rule_type=RuleType.keyword, weight=1, is_optional=False, is_critical=False,
        requires_evidence=False, keywords={"phrases": ["hello"], "mode": "must_include"},
        speaker_scope=SpeakerScope.any, scoring_logic=ScoringLogic.pass_fail,
        evaluation_mode=EvaluationMode.automatic, order_index=0,
    )
    db_session.add(criterion)
    db_session.commit()

    # Simulate a first, never-reviewed run (e.g. a prior attempt that crashed after
    # this point but before the pipeline step was marked succeeded).
    first_evaluation = await run_scorecard(db_session, call, scorecard)
    first_id = first_evaluation.id

    # Retry: run_scorecard again for the same call+scorecard.
    second_evaluation = await run_scorecard(db_session, call, scorecard)

    remaining = db_session.query(QAEvaluation).filter(QAEvaluation.call_id == call.id).all()
    assert len(remaining) == 1, "retry must replace the unreviewed evaluation, not duplicate it"
    assert remaining[0].id == second_evaluation.id
    assert db_session.get(QAEvaluation, first_id) is None
