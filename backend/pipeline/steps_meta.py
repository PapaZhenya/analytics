"""Shared step metadata used by both the orchestrator (writes progress) and the API's
GET /calls/{id}/status endpoint (reads it) — single source of truth for step
names/order/coarse-status mapping so the two never drift apart.
"""
from backend.app.models.calls import CallStatus

# Ordered, flat breakdown of main.py's original 18 (numbered) pipeline steps — some of
# main.py's numbered steps (7.1-7.4, 17.1-17.2) are broken out individually here so each
# gets its own call_processing_steps row / resumability checkpoint.
STEP_NAMES: list[str] = [
    "dialogue_detection",
    "speech_enhancement",
    "vocal_separation",
    "transcription",
    "forced_alignment",
    "diarization",
    "speaker_timestamps",
    "word_speaker_mapping",
    "punctuation_restoration",
    "sentence_speaker_mapping",
    "export_transcript",
    "classify_speaker_roles",
    "sentiment_analysis",
    "profanity_detection",
    "summary",
    "conflict_detection",
    "topic_detection",
    "acoustic_metrics",
    "silence_metrics",
    "persist_results",
    "qa_evaluation",
]

STEP_SEQUENCE: dict[str, int] = {name: i for i, name in enumerate(STEP_NAMES)}

# Which coarse calls.status a given fine-grained step belongs to, for the UI's status badge.
STEP_TO_CALL_STATUS: dict[str, CallStatus] = {
    "dialogue_detection": CallStatus.preprocessing,
    "speech_enhancement": CallStatus.preprocessing,
    "vocal_separation": CallStatus.preprocessing,
    "transcription": CallStatus.transcribing,
    "forced_alignment": CallStatus.aligning,
    "diarization": CallStatus.diarizing,
    "speaker_timestamps": CallStatus.assigning_speakers,
    "word_speaker_mapping": CallStatus.assigning_speakers,
    "punctuation_restoration": CallStatus.assigning_speakers,
    "sentence_speaker_mapping": CallStatus.assigning_speakers,
    "export_transcript": CallStatus.assigning_speakers,
    "classify_speaker_roles": CallStatus.assigning_speakers,
    "sentiment_analysis": CallStatus.analyzing,
    "profanity_detection": CallStatus.analyzing,
    "summary": CallStatus.analyzing,
    "conflict_detection": CallStatus.analyzing,
    "topic_detection": CallStatus.analyzing,
    "acoustic_metrics": CallStatus.analyzing,
    "silence_metrics": CallStatus.analyzing,
    "qa_evaluation": CallStatus.analyzing,
    "persist_results": CallStatus.analyzing,
}
