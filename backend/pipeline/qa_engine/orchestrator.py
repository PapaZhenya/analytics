import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from backend.app.models.qa import (
    EvaluationStatus,
    QAEvaluation,
    QAFinding,
    QAFindingEvidence,
    RuleType,
    Scorecard,
    Verdict,
)
from backend.pipeline.context import PipelineContext
from backend.pipeline.qa_engine.base import CallContext
from backend.pipeline.qa_engine.keyword_evaluator import KeywordEvaluator
from backend.pipeline.qa_engine.semantic_evaluator import SemanticEvaluator

# Phase 1 implements exactly these two rule types end-to-end. Every other RuleType
# enum value (regex, sequence, timing, silence_interruption, speaker_behavior,
# script_compliance, hybrid, manual_only) is a pure future addition: a new evaluator
# module registered here, never a change to this orchestrator's structure.
_EVALUATORS = {
    RuleType.keyword: KeywordEvaluator(),
    RuleType.semantic: SemanticEvaluator(),
}


class UnsupportedRuleTypeError(Exception):
    pass


def _clear_unreviewed_evaluation(db, call_id: uuid.UUID, scorecard_id: uuid.UUID) -> None:
    """Idempotency for retries: if the qa_evaluation pipeline step previously started
    and failed partway (e.g. a semantic evaluator call errored on criterion 5 of 10),
    a naive retry would leave that partial QAEvaluation/QAFinding orphaned in the DB
    while also inserting a second, complete one. Since this only ever removes
    evaluations with `status == pending_review` AND zero review_actions logged against
    any of their findings, it can never touch a result a human has actually looked at —
    that's what "do not silently alter historical QA results" actually requires here:
    protecting reviewed data, not freezing every unreviewed row forever."""
    from backend.app.models.qa import ReviewAction

    stale = (
        db.query(QAEvaluation)
        .filter(QAEvaluation.call_id == call_id, QAEvaluation.scorecard_id == scorecard_id)
        .all()
    )
    for evaluation in stale:
        has_review_activity = (
            db.query(ReviewAction)
            .join(QAFinding, ReviewAction.finding_id == QAFinding.id)
            .filter(QAFinding.evaluation_id == evaluation.id)
            .first()
            is not None
        )
        if evaluation.status == EvaluationStatus.pending_review and not has_review_activity:
            db.delete(evaluation)
    db.flush()


async def run_scorecard(db, call, scorecard: Scorecard) -> QAEvaluation:
    context = CallContext.load(db, call.id)

    _clear_unreviewed_evaluation(db, call.id, scorecard.id)

    evaluation = QAEvaluation(
        id=uuid.uuid4(),
        call_id=call.id,
        scorecard_id=scorecard.id,
        status=EvaluationStatus.pending_review,
    )
    db.add(evaluation)
    db.flush()

    total_weight = 0.0
    earned_weight = 0.0
    auto_failed = False

    for section in scorecard.sections:
        for criterion in section.criteria:
            evaluator = _EVALUATORS.get(criterion.rule_type)
            if evaluator is None:
                # Not-yet-implemented rule type (Phase 2+) or manual_only — recorded as a
                # pending manual finding rather than silently skipped.
                result_verdict = Verdict.na
                explanation = (
                    f"Rule type '{criterion.rule_type.value}' has no automatic evaluator in "
                    "Phase 1 — awaiting manual review."
                )
                confidence = None
                evidence_rows = []
                engine_version = "manual-only"
            else:
                result = await evaluator.evaluate(criterion, context)
                result_verdict = Verdict(result.verdict)
                explanation = result.explanation
                confidence = result.confidence
                engine_version = result.engine_version
                evidence_rows = result.evidence

            finding = QAFinding(
                id=uuid.uuid4(),
                evaluation_id=evaluation.id,
                criterion_id=criterion.id,
                ai_verdict=result_verdict,
                ai_confidence=confidence,
                ai_explanation=explanation,
                engine_version=engine_version,
                current_verdict=result_verdict,
                human_corrected=False,
            )
            db.add(finding)
            db.flush()

            for ev in evidence_rows:
                db.add(
                    QAFindingEvidence(
                        id=uuid.uuid4(),
                        finding_id=finding.id,
                        utterance_id=ev.utterance_id,
                        start_time=ev.start_time,
                        end_time=ev.end_time,
                        quote_text=ev.quote_text,
                        evidence_type=ev.evidence_type,
                    )
                )

            if result_verdict != Verdict.na and not criterion.is_optional:
                total_weight += float(criterion.weight)
                if result_verdict == Verdict.pass_:
                    earned_weight += float(criterion.weight)
                elif criterion.is_critical:
                    auto_failed = True

    evaluation.max_score = 100.0
    evaluation.overall_score = 0.0 if auto_failed else (
        round(100.0 * earned_weight / total_weight, 2) if total_weight > 0 else None
    )
    db.commit()
    return evaluation


async def run_default_scorecard(ctx: PipelineContext) -> None:
    """Called from the orchestrator's qa_evaluation step: picks the active scorecard
    for the call's project and runs it. If a project has no published/active scorecard
    yet, this is a no-op — the call still completes, just without a QA evaluation."""
    db = ctx.db
    call = ctx.call

    scorecard = db.execute(
        select(Scorecard)
        .where(Scorecard.project_id == call.project_id, Scorecard.is_active.is_(True))
        .order_by(Scorecard.version.desc())
        .limit(1)
    ).scalar_one_or_none()

    if scorecard is None:
        return

    await run_scorecard(db, call, scorecard)
