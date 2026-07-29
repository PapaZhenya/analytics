"""Section 8 requires historical reports stay explainable: who changed a result and
when, not just its current state. These exercise the two history endpoints end to end
through the actual API (not just the ORM), since that's what a manager would use."""
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.tests.conftest import requires_postgres


def _make_client(db_session_override) -> TestClient:
    from backend.app.db.session import get_db
    from backend.app.main import app

    def _override():
        yield db_session_override

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


@requires_postgres
def test_finding_history_shows_every_review_action_in_order(db_session, seed_reference_data):
    from backend.app.models.calls import Call, CallSource, CallStatus, Speaker, Utterance
    from backend.app.models.org import Project, User
    from backend.app.models.qa import (
        EvaluationMode,
        EvaluationStatus,
        QAEvaluation,
        QAFinding,
        RuleType,
        Scorecard,
        ScorecardCriterion,
        ScorecardSection,
        ScoringLogic,
        SpeakerScope,
        Verdict,
    )
    from backend.app.security import hash_password

    org = seed_reference_data["org"]
    project = Project(id=uuid.uuid4(), org_id=org.id, name="History Test Project")
    reviewer = User(
        id=uuid.uuid4(), org_id=org.id, email="history-reviewer@example.com",
        password_hash=hash_password("s3cret!"), full_name="Reviewer",
        role_id=seed_reference_data["roles"]["qa_reviewer"].id,
    )
    db_session.add_all([project, reviewer])
    db_session.commit()

    call = Call(
        id=uuid.uuid4(), org_id=org.id, project_id=project.id, uploaded_by=reviewer.id,
        source=CallSource.upload, original_filename="t.mp3", storage_path="t.mp3",
        checksum="b" * 64, status=CallStatus.completed, uploaded_at=datetime.now(timezone.utc),
    )
    db_session.add(call)
    db_session.commit()

    scorecard = Scorecard(
        id=uuid.uuid4(), group_id=uuid.uuid4(), version=1, name="SC", project_id=project.id,
        is_active=True, created_by=reviewer.id,
    )
    db_session.add(scorecard)
    db_session.flush()
    section = ScorecardSection(id=uuid.uuid4(), scorecard_id=scorecard.id, name="S", order_index=0, weight=1)
    db_session.add(section)
    db_session.flush()
    criterion = ScorecardCriterion(
        id=uuid.uuid4(), section_id=section.id, code="c1", text="Test", rule_type=RuleType.keyword,
        weight=1, is_optional=False, is_critical=False, requires_evidence=False,
        speaker_scope=SpeakerScope.any, scoring_logic=ScoringLogic.pass_fail,
        evaluation_mode=EvaluationMode.automatic, order_index=0,
    )
    db_session.add(criterion)
    db_session.flush()
    evaluation = QAEvaluation(
        id=uuid.uuid4(), call_id=call.id, scorecard_id=scorecard.id, status=EvaluationStatus.pending_review,
    )
    db_session.add(evaluation)
    db_session.flush()
    finding = QAFinding(
        id=uuid.uuid4(), evaluation_id=evaluation.id, criterion_id=criterion.id,
        ai_verdict=Verdict.fail, engine_version="1.0", current_verdict=Verdict.fail,
        human_corrected=False,
    )
    db_session.add(finding)
    db_session.commit()

    client = _make_client(db_session)
    token = _login(client, "history-reviewer@example.com", "s3cret!")
    headers = {"Authorization": f"Bearer {token}"}

    # Reviewer disagrees, corrects it, then reopens.
    r1 = client.post(f"/api/v1/findings/{finding.id}/review", json={"action": "correct", "new_verdict": "pass", "notes": "listened again"}, headers=headers)
    assert r1.status_code == 200
    r2 = client.post(f"/api/v1/findings/{finding.id}/review", json={"action": "reopen"}, headers=headers)
    assert r2.status_code == 200

    history_response = client.get(f"/api/v1/findings/{finding.id}/history", headers=headers)
    assert history_response.status_code == 200
    history = history_response.json()

    assert len(history) == 2
    assert history[0]["action_type"] == "correct"
    assert history[0]["previous_verdict"] == "fail"
    assert history[0]["new_verdict"] == "pass"
    assert history[0]["user_id"] == str(reviewer.id)
    assert history[1]["action_type"] == "reopen"


@requires_postgres
def test_utterance_correction_history_preserves_every_revision(db_session, seed_reference_data):
    from backend.app.models.calls import Call, CallSource, CallStatus, Speaker, SpeakerRole, Utterance
    from backend.app.models.org import Project, User
    from backend.app.security import hash_password

    org = seed_reference_data["org"]
    project = Project(id=uuid.uuid4(), org_id=org.id, name="Correction History Project")
    reviewer = User(
        id=uuid.uuid4(), org_id=org.id, email="corr-reviewer@example.com",
        password_hash=hash_password("s3cret!"), full_name="Reviewer",
        role_id=seed_reference_data["roles"]["qa_reviewer"].id,
    )
    db_session.add_all([project, reviewer])
    db_session.commit()

    call = Call(
        id=uuid.uuid4(), org_id=org.id, project_id=project.id, uploaded_by=reviewer.id,
        source=CallSource.upload, original_filename="t.mp3", storage_path="t.mp3",
        checksum="c" * 64, status=CallStatus.completed, uploaded_at=datetime.now(timezone.utc),
    )
    db_session.add(call)
    db_session.commit()

    agent_role = db_session.query(SpeakerRole).filter(SpeakerRole.code == "agent").one()
    speaker = Speaker(id=uuid.uuid4(), call_id=call.id, diarization_label="Speaker 0", role_id=agent_role.id)
    db_session.add(speaker)
    db_session.flush()
    utterance = Utterance(
        id=uuid.uuid4(), call_id=call.id, speaker_id=speaker.id, sequence=0,
        start_time=0, end_time=1, original_content="orignal asr text", is_profane=False,
    )
    db_session.add(utterance)
    db_session.commit()

    client = _make_client(db_session)
    token = _login(client, "corr-reviewer@example.com", "s3cret!")
    headers = {"Authorization": f"Bearer {token}"}

    r1 = client.post(
        f"/api/v1/calls/{call.id}/utterances/{utterance.id}/correct",
        json={"corrected_content": "first fix", "reason": "typo"},
        headers=headers,
    )
    assert r1.status_code == 200
    r2 = client.post(
        f"/api/v1/calls/{call.id}/utterances/{utterance.id}/correct",
        json={"corrected_content": "second fix", "reason": "still wrong"},
        headers=headers,
    )
    assert r2.status_code == 200

    history_response = client.get(
        f"/api/v1/calls/{call.id}/utterances/{utterance.id}/history", headers=headers
    )
    assert history_response.status_code == 200
    history = history_response.json()

    assert len(history) == 2
    assert history[0]["corrected_content"] == "first fix"
    assert history[1]["corrected_content"] == "second fix"
    assert history[0]["corrected_by"] == str(reviewer.id)

    # The original ASR text must never be overwritten by a correction.
    db_session.refresh(utterance)
    assert utterance.original_content == "orignal asr text"
