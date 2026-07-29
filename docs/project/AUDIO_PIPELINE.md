# Audio & Speech Pipeline — Stage Mapping and Known Limitations

Section 5 of the product spec requires the pipeline decomposed into 14 explicit stages,
and requires being honest about what's actually handled vs. not — "do not claim perfect
speaker identification." This maps each requested stage onto the concrete
implementation (`backend/pipeline/steps.py`, `backend/pipeline/steps_meta.py::STEP_NAMES`)
and states plainly what's a real capability vs. a documented gap.

## Stage-by-stage mapping

| # | Requested stage | Implementation | Status |
|---|---|---|---|
| 1 | File validation | `step_file_validation` — `soundfile.info()` decode check + minimum-duration check, **new in this pass** | ✅ Real, dedicated step |
| 2 | Normalization | Implicit inside `SpeechEnhancement`/`Transcriber` (each resamples to its own model's required rate internally) | ⚠️ Not a dedicated step — exists only as a side effect of downstream library calls, not a standalone normalization pass with its own output/checkpoint |
| 3 | Optional noise reduction | `step_speech_enhancement` (MPSENet, `src/audio/preprocessing.py`) — skipped automatically below a noise-level threshold | ✅ Real, dedicated step, genuinely optional (threshold-gated) |
| 4 | Channel inspection | `step_channel_inspection` — records `channels`, and a correlation-based `is_separate_channel_recording` heuristic, **new in this pass** | ⚠️ Detected and persisted (`calls.channel_count`, `calls.is_separate_channel_recording`), but **not yet used to change processing** — see "Known limitation: channel-aware routing" below |
| 5 | Voice activity detection | Embedded inside `faster_whisper` (`vad_filter=True`) and inside NeMo's diarizer (its own VAD model) | ⚠️ Real, but distributed across two libraries rather than one dedicated pipeline stage with its own output |
| 6 | Diarization | `step_diarization` (NeMo `NeuralDiarizer`, `diar_infer_telephonic.yaml`) | ✅ Real, dedicated step — see overlapping-speech limitation below |
| 7 | Transcription | `step_transcription` (`faster-whisper large-v3`) | ✅ Real, dedicated step |
| 8 | Timestamp alignment | `step_forced_alignment` (`ctc_forced_aligner`) | ✅ Real, dedicated step |
| 9 | Speaker mapping | `step_word_speaker_mapping` + `step_punctuation_restoration` + `step_sentence_speaker_mapping` | ✅ Real, three dedicated steps (word-level, punctuation-aware realignment, sentence-level) |
| 10 | Agent/Client role assignment | `step_classify_speaker_roles` (LLM classification + fallback heuristic) | ✅ Real, **with exposed uncertainty** — see `Speaker.role_confidence` below |
| 11 | Transcript persistence | `persist_results` (part of `backend/pipeline/orchestrator.py::_persist_results`) | ✅ Real — `speakers`/`utterances` tables |
| 12 | Quality metrics | `step_acoustic_metrics` + `step_silence_metrics` | ✅ Real, two dedicated steps (acoustic features + silence/interruption/talk-ratio) |
| 13 | QA analysis | `qa_evaluation` (`backend/pipeline/qa_engine/`) | ✅ Real, dedicated step, schema-validated (see `MODULES.md`/`WEB_PLATFORM.md`) |
| 14 | Result persistence | `persist_results` (same step as #11 — QA findings are persisted separately by the `qa_evaluation` step immediately after) | ✅ Real |

## Uncertainty is exposed, not hidden

- **`Speaker.role_confidence`** (nullable float, `backend/app/models/calls.py`) — a
  **heuristic tier, not a calibrated probability**: `0.85` when the LLM Classification
  step's result validated cleanly, `0.3` when `LLMResultHandler` (unmodified) had to
  fall back to its "first speaker = CSR" heuristic, `1.0` once a human confirms/corrects
  it. The review UI (`TranscriptPanel`'s speaker-role summary) shows a "⚠ uncertain"
  badge below a 0.5 threshold, and a "Fix role" control
  (`POST /calls/{id}/speakers/{id}/correct-role`) lets a reviewer correct a whole
  speaker's role directly — logged to `audit_log` (old role, new role, reviewer,
  reason) — rather than requiring them to fix every individual utterance by hand.
- **Per-utterance correction** (`UtteranceCorrection`, already existed) covers the
  finer-grained case: diarization/transcription got one specific line wrong.
- **Failed diarization / failed transcription** surface as a cleanly failed
  `call_processing_steps` row with `error_message` set and `calls.status = 'failed'` —
  visible in the review UI's processing-status panel — never as a silently wrong or
  fabricated result.

## Model version tracking

`Call.model_versions` (JSONB) accumulates `{"speech_enhancement": ..., "whisper":
"large-v3", "alignment": "ctc_forced_aligner_default", "diarization": "diar_msdd_telephonic",
"llm_provider": "llama"}` as each step runs, so "which model version processed this
specific historical call" is answerable after the fact — important once models get
upgraded and old calls need to be understood in the context of what actually produced
them.

## GPU/CPU and transcription retries

- **GPU/CPU**: every model-bearing class (`SpeechEnhancement`, `Transcriber`,
  `ForcedAligner`, NeMo's diarizer) reads `config/config.yaml`'s `runtime.device` —
  unchanged from the original repo, already correct.
- **Transcription retries**: not a special case — the orchestrator's general
  idempotent-step design (`backend/pipeline/orchestrator.py`) means if `transcription`
  fails, only that step (and everything after it) re-runs on the next attempt;
  `speech_enhancement`/`vocal_separation` etc. are skipped as already-succeeded. Celery
  retries the whole task (`max_retries=3`) on any step failure.
- **Long calls**: `pipeline_task_soft_time_limit_seconds` /
  `pipeline_task_time_limit_seconds` (`backend/app/config.py`, defaults 110min/120min)
  bound worst-case processing time; a soft-limit timeout fails the call immediately with
  a clear reason instead of being retried (retrying something inherently too slow just
  times out again).

## Known limitations (documented, not silently glossed over)

- **Overlapping speech**: `config/nemo/diar_infer_telephonic.yaml` sets
  `diarizer.ignore_overlap: True` (unchanged, original repo default) — overlapping
  speech regions are assigned to a single speaker, not flagged as overlapping. Flipping
  this would require `WordSpeakerMapper` (unmodified, per the approved plan) to handle
  multiple simultaneous speakers per time span, which it doesn't today. Not fixed in
  this pass; a real capability gap, stated plainly rather than assumed away.
- **Channel-aware routing**: `step_channel_inspection` detects and persists whether a
  recording is likely two independent per-speaker channels (e.g. agent on left, client
  on right — a common telephony format) via a left/right correlation heuristic, but the
  pipeline does **not yet branch** on this signal — `AudioProcessor.convert_to_mono()`
  still always folds to mono before diarization regardless. A genuinely
  separate-channel recording would be *more* reliably split by channel than by
  diarization, but building that alternate processing path (skip diarization, transcribe
  each channel independently, treat channel = speaker) is a bigger, separate change
  flagged here as a natural next step, not attempted in this pass to avoid destabilizing
  the existing, working diarization-based path for the (likely more common) mono/mixed
  case.
- **Poor audio**: `SpeechEnhancement` (MPSENet) and `DemucsVocalSeparator` improve poor
  audio where they can, but there's no explicit "this call's audio quality was too poor
  to transcribe reliably" signal surfaced anywhere — a low-confidence transcription
  today looks the same as a high-confidence one to a reviewer, beyond judging the
  acoustic metrics (`acoustic_metrics` table) themselves.
- **Multiple languages**: handled — `faster-whisper` auto-detects language per call
  (`Call.detected_language`); no per-call language configuration is needed. Not
  verified against a real multi-language audio sample in this session (no GPU/ML
  environment available here — see `WEB_PLATFORM.md`).
