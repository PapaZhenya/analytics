"""Deterministic keyword/phrase rule type.

criterion.keywords contract: {"phrases": ["thank you for calling", ...],
                               "mode": "must_include" | "must_avoid"}  # default must_include
"""
from backend.pipeline.qa_engine.base import CallContext, RuleEvaluator
from backend.pipeline.qa_engine.schemas import CriterionResult, EvidenceSpan


class KeywordEvaluator(RuleEvaluator):
    async def evaluate(self, criterion, context: CallContext) -> CriterionResult:
        config = criterion.keywords or {}
        phrases = [p.lower() for p in config.get("phrases", [])]
        mode = config.get("mode", "must_include")

        scoped_utterances = context.utterances_for_scope(criterion.speaker_scope.value)

        matches: list[EvidenceSpan] = []
        for utterance in scoped_utterances:
            text_lower = utterance.original_content.lower()
            for phrase in phrases:
                if phrase in text_lower:
                    matches.append(
                        EvidenceSpan(
                            utterance_id=utterance.id,
                            start_time=float(utterance.start_time),
                            end_time=float(utterance.end_time),
                            quote_text=utterance.original_content,
                            evidence_type="positive" if mode == "must_include" else "violation",
                        )
                    )

        found = len(matches) > 0
        if mode == "must_include":
            verdict = "pass" if found else "fail"
            explanation = (
                f"Found {len(matches)} match(es) for required phrase(s)."
                if found
                else "None of the required phrases were found."
            )
        else:  # must_avoid
            verdict = "fail" if found else "pass"
            explanation = (
                f"Found {len(matches)} occurrence(s) of a disallowed phrase."
                if found
                else "No disallowed phrases were found."
            )

        if criterion.requires_evidence and verdict == "fail" and not matches:
            # No evidence to attach for an absence-based failure — record the omission
            # explicitly rather than silently leaving evidence empty.
            explanation += " (Criterion requires evidence; failure is due to absence, not a quoted violation.)"

        return CriterionResult(
            criterion_id=criterion.id,
            verdict=verdict,
            explanation=explanation,
            evidence=matches,
            confidence=1.0,  # deterministic rule — always fully confident
            engine_version=self.engine_version,
        )
