"""Validates raw LLM JSON output (from the existing, unmodified src/text/llm.py
LLMOrchestrator) before any of it is persisted or used to compute a QA score.

Without this, a single malformed item from the model (e.g. a sentiment object missing
"index", or a nonstandard sentiment label) crashes the whole persist_results step with
an unhandled KeyError — not a graceful validation failure, an unstructured application
error. Each item is validated independently: one bad item is logged and skipped, not
treated as reason to discard everything else the model got right.
"""
import logging
from typing import Literal

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


class SentimentItem(BaseModel):
    index: int
    sentiment: Literal["Neutral", "Positive", "Negative"]


class ProfanityItem(BaseModel):
    index: int
    profane: bool


class SummaryResult(BaseModel):
    summary: str


class ConflictResult(BaseModel):
    conflict: bool


class TopicResult(BaseModel):
    topic: str


def parse_indexed_items(raw_items: list, model: type[BaseModel], *, context: str) -> list[BaseModel]:
    """Validates each item in a raw LLM-returned list independently — malformed items
    are logged and dropped rather than crashing the whole batch or being trusted as-is."""
    validated = []
    for item in raw_items:
        try:
            validated.append(model.model_validate(item))
        except ValidationError as exc:
            logger.warning(
                "Discarding malformed LLM output item",
                extra={"context": context, "raw_item": item, "error": str(exc)},
            )
    return validated


def parse_single(raw: dict | None, model: type[BaseModel], *, context: str) -> BaseModel | None:
    if not raw:
        return None
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        logger.warning(
            "Discarding malformed LLM output",
            extra={"context": context, "raw": raw, "error": str(exc)},
        )
        return None
