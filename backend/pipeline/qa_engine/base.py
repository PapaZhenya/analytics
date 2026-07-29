import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.app.models.calls import AcousticMetrics, Speaker, Utterance
from backend.app.models.qa import ScorecardCriterion


@dataclass
class CallContext:
    """Bundles everything a rule evaluator might need to reference, regardless of
    rule_type — persisted utterances/speakers (with real DB ids, so evidence can point
    at them), acoustic/silence metrics, and per-utterance sentiment/profanity signals
    already produced by the existing pipeline steps."""

    call_id: uuid.UUID
    utterances: list[Utterance]
    speakers_by_id: dict[uuid.UUID, Speaker]
    acoustic_metrics: AcousticMetrics | None

    @classmethod
    def load(cls, db: Session, call_id: uuid.UUID) -> "CallContext":
        utterances = (
            db.query(Utterance)
            .filter(Utterance.call_id == call_id)
            .order_by(Utterance.sequence)
            .all()
        )
        speakers = db.query(Speaker).filter(Speaker.call_id == call_id).all()
        metrics = db.query(AcousticMetrics).filter(AcousticMetrics.call_id == call_id).one_or_none()
        return cls(
            call_id=call_id,
            utterances=utterances,
            speakers_by_id={s.id: s for s in speakers},
            acoustic_metrics=metrics,
        )

    def speaker_role_code(self, utterance: Utterance) -> str:
        speaker = self.speakers_by_id.get(utterance.speaker_id)
        return speaker.role.code if speaker and speaker.role else "unknown"

    def utterances_for_scope(self, speaker_scope: str) -> list[Utterance]:
        if speaker_scope == "any":
            return self.utterances
        return [u for u in self.utterances if self.speaker_role_code(u) == speaker_scope]


class RuleEvaluator(ABC):
    """One implementation per scorecard_criteria.rule_type. Adding a new rule type is a
    pure addition — a new evaluator module plus a RuleType enum value — never a change to
    this interface, orchestrator.py, or any other evaluator."""

    engine_version: str = "1.0"

    @abstractmethod
    async def evaluate(self, criterion: ScorecardCriterion, context: CallContext):
        """Returns a backend.pipeline.qa_engine.schemas.CriterionResult."""
