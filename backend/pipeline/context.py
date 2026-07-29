from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.calls import Call


@dataclass
class PipelineContext:
    """Carries in-memory state between step functions within a single run_pipeline() call.
    Mirrors the local variables main.py's async def main() used to pass between its
    inline steps — now split across step functions so each can be individually retried/
    resumed via call_processing_steps.
    """

    db: Session
    call: Call
    call_id: str
    temp_dir: str
    original_audio_path: str

    # Populated by step_file_validation / step_channel_inspection (stages 1 and 4 of
    # the required pipeline decomposition) and persisted onto the Call row itself
    # (backend/app/models/calls.py) rather than only living in this in-memory context.
    channel_count: int | None = None
    is_separate_channel_recording: bool | None = None
    model_versions: dict[str, str] = field(default_factory=dict)

    # Set by step_classify_speaker_roles: whether LLMResultHandler's real classification
    # validated (False) or it had to fall back to its first-speaker-is-CSR heuristic
    # (True) — the honest signal behind Speaker.role_confidence (see that field's
    # docstring for why this, not a fabricated probability).
    role_assignment_used_fallback: bool | None = None

    enhanced_audio_path: str | None = None
    vocal_audio_path: str | None = None
    mono_audio_path: str | None = None
    transcript: str | None = None
    detected_language: str | None = None
    word_timestamps: list[dict] | None = None
    rttm_path: str | None = None
    speaker_timestamps: list[list] | None = None
    word_speaker_mapping: list[dict] | None = None
    sentence_speaker_mapping: list[dict] | None = None  # ssm

    speaker_roles_raw: dict[str, Any] | None = None  # {"Customer": "Speaker 0", "CSR": "Speaker 1"}
    sentiment_results: dict[str, Any] | None = None
    profanity_results: dict[str, Any] | None = None
    summary_result: dict[str, Any] | None = None
    conflict_result: dict[str, Any] | None = None
    topic_result: dict[str, Any] | None = None
    final_output: dict[str, Any] | None = None

    acoustic_properties: tuple | None = None
    silence_threshold: float | None = None
    interruption_count: int = 0
    agent_talk_ratio: float | None = None
