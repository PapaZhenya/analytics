"""Exercises the QA rule engine's keyword evaluator and CriterionResult schema
validation using plain, unpersisted ORM objects — no database required, since these
evaluators only ever read the Python objects handed to them via CallContext."""
import uuid

import pytest
from pydantic import ValidationError

from backend.app.models.calls import Speaker, SpeakerRole, Utterance
from backend.app.models.qa import RuleType, ScorecardCriterion, ScoringLogic, SpeakerScope, EvaluationMode
from backend.pipeline.qa_engine.base import CallContext
from backend.pipeline.qa_engine.keyword_evaluator import KeywordEvaluator
from backend.pipeline.qa_engine.schemas import CriterionResult


def _make_utterance(text: str, speaker: Speaker, start: float, end: float, seq: int) -> Utterance:
    u = Utterance(
        id=uuid.uuid4(),
        call_id=speaker.call_id,
        speaker_id=speaker.id,
        sequence=seq,
        start_time=start,
        end_time=end,
        original_content=text,
        is_profane=False,
    )
    return u


def _agent_speaker(call_id) -> Speaker:
    role = SpeakerRole(id=uuid.uuid4(), code="agent", label="Agent")
    speaker = Speaker(id=uuid.uuid4(), call_id=call_id, diarization_label="Speaker 0")
    speaker.role = role
    return speaker


def _keyword_criterion(phrases: list[str], mode: str = "must_include") -> ScorecardCriterion:
    return ScorecardCriterion(
        id=uuid.uuid4(),
        section_id=uuid.uuid4(),
        code="greeting",
        text="Agent greets the caller",
        rule_type=RuleType.keyword,
        weight=1,
        is_optional=False,
        is_critical=False,
        requires_evidence=True,
        keywords={"phrases": phrases, "mode": mode},
        speaker_scope=SpeakerScope.agent,
        scoring_logic=ScoringLogic.pass_fail,
        evaluation_mode=EvaluationMode.automatic,
        order_index=0,
    )


@pytest.mark.asyncio
async def test_keyword_evaluator_passes_when_phrase_present():
    call_id = uuid.uuid4()
    agent = _agent_speaker(call_id)
    utterance = _make_utterance("Thank you for calling, how can I help you?", agent, 0, 3, 0)

    context = CallContext(
        call_id=call_id, utterances=[utterance], speakers_by_id={agent.id: agent}, acoustic_metrics=None
    )
    criterion = _keyword_criterion(["thank you for calling"])

    result = await KeywordEvaluator().evaluate(criterion, context)

    assert result.verdict == "pass"
    assert len(result.evidence) == 1
    assert result.evidence[0].utterance_id == utterance.id
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_keyword_evaluator_fails_when_phrase_absent():
    call_id = uuid.uuid4()
    agent = _agent_speaker(call_id)
    utterance = _make_utterance("Hello there.", agent, 0, 1, 0)

    context = CallContext(
        call_id=call_id, utterances=[utterance], speakers_by_id={agent.id: agent}, acoustic_metrics=None
    )
    criterion = _keyword_criterion(["thank you for calling"])

    result = await KeywordEvaluator().evaluate(criterion, context)

    assert result.verdict == "fail"
    assert result.evidence == []


@pytest.mark.asyncio
async def test_keyword_evaluator_must_avoid_mode_flags_violation():
    call_id = uuid.uuid4()
    agent = _agent_speaker(call_id)
    utterance = _make_utterance("I don't care about your problem.", agent, 0, 2, 0)

    context = CallContext(
        call_id=call_id, utterances=[utterance], speakers_by_id={agent.id: agent}, acoustic_metrics=None
    )
    criterion = _keyword_criterion(["i don't care"], mode="must_avoid")

    result = await KeywordEvaluator().evaluate(criterion, context)

    assert result.verdict == "fail"
    assert result.evidence[0].evidence_type == "violation"


def test_criterion_result_rejects_malformed_verdict():
    """The whole point of schema validation: an evaluator (or a buggy future one) that
    tries to emit anything other than pass/fail/na must be rejected, not persisted."""
    with pytest.raises(ValidationError):
        CriterionResult(
            criterion_id=uuid.uuid4(),
            verdict="definitely maybe",  # not pass/fail/na
            explanation="unstructured nonsense",
            engine_version="1.0",
        )


def test_criterion_result_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        CriterionResult(
            criterion_id=uuid.uuid4(),
            verdict="pass",
            explanation="ok",
            confidence=1.5,
            engine_version="1.0",
        )
