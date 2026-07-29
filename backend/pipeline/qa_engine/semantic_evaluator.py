"""LLM-assisted rule type. Unlike the original pipeline's 6 fixed prompts
(config/prompt.yaml, used unchanged by src/text/llm.py::LLMOrchestrator for
Classification/SentimentAnalysis/etc.), this builds one prompt per scorecard criterion
from criterion.semantic_instruction — but every response still goes through the same
CriterionResult schema validation as every other rule type. A model returning prose
instead of the expected JSON shape simply fails validation and never reaches qa_findings.
"""
from backend.app.config import get_settings
from backend.pipeline.qa_engine.base import CallContext, RuleEvaluator
from backend.pipeline.qa_engine.schemas import CriterionResult, EvidenceSpan

settings = get_settings()

_SYSTEM_TEMPLATE = """You are a call-center QA evaluator. Evaluate the conversation below \
against exactly one criterion.

Criterion: {instruction}

Respond with ONLY a JSON object, no other text, in this exact shape:
{{
  "verdict": "pass" | "fail" | "na",
  "explanation": "<one or two sentences>",
  "confidence": <0.0-1.0>,
  "evidence": [{{"quote": "<exact quoted text from the transcript>"}}]
}}
If the criterion does not apply to this conversation, use "na" and an empty evidence list.
"""


class SemanticEvaluator(RuleEvaluator):
    async def evaluate(self, criterion, context: CallContext) -> CriterionResult:
        from src.audio.utils import Formatter
        from src.text.llm import LLMOrchestrator

        llm = LLMOrchestrator(
            config_path=settings.pipeline_config_path,
            prompt_config_path=settings.pipeline_prompt_path,
            model_id="openai",
        )

        scoped = context.utterances_for_scope(criterion.speaker_scope.value)
        dialogue_input = [
            {"speaker": context.speaker_role_code(u), "text": u.original_content} for u in scoped
        ]
        dialogue_text = Formatter.format_ssm_as_dialogue(dialogue_input)

        system_prompt = _SYSTEM_TEMPLATE.format(instruction=criterion.semantic_instruction or criterion.text)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": dialogue_text},
        ]

        raw_response = await llm.manager.generate(model_id="openai", messages=messages, max_new_tokens=1000)

        parsed = LLMOrchestrator.extract_json(raw_response) if raw_response else None
        if not parsed or "verdict" not in parsed:
            # Malformed/unstructured model output — explicit fail-closed, never persisted
            # as a false pass. This is the concrete enforcement of "no criterion may
            # receive a result merely because an AI model produced unstructured prose."
            return CriterionResult(
                criterion_id=criterion.id,
                verdict="na",
                explanation="Model response could not be parsed as the required JSON shape.",
                evidence=[],
                confidence=0.0,
                engine_version=self.engine_version,
            )

        evidence: list[EvidenceSpan] = []
        for item in parsed.get("evidence", []) or []:
            quote = item.get("quote", "") if isinstance(item, dict) else ""
            if not quote:
                continue
            match = next((u for u in scoped if quote.strip() in u.original_content), None)
            if match is not None:
                evidence.append(
                    EvidenceSpan(
                        utterance_id=match.id,
                        start_time=float(match.start_time),
                        end_time=float(match.end_time),
                        quote_text=quote,
                        evidence_type="violation" if parsed.get("verdict") == "fail" else "positive",
                    )
                )

        verdict = parsed.get("verdict")
        if verdict not in ("pass", "fail", "na"):
            verdict = "na"

        confidence = parsed.get("confidence")
        try:
            confidence = float(confidence) if confidence is not None else None
            if confidence is not None:
                confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = None

        return CriterionResult(
            criterion_id=criterion.id,
            verdict=verdict,
            explanation=str(parsed.get("explanation", ""))[:2000],
            evidence=evidence,
            confidence=confidence,
            engine_version=self.engine_version,
        )
