"""Thin adapters over the existing, UNMODIFIED src/audio/* and src/text/* classes.

Every function here is a 1:1 port of the corresponding step in the original main.py,
just reading/writing a PipelineContext instead of local variables, so it can be resumed
step-by-step (see backend/pipeline/orchestrator.py). No pipeline class from src/ is
edited to support this — only how they're *called* changes (permanent storage path
instead of a watch-folder path, delete_original left at its default False).
"""
import os

from omegaconf import OmegaConf

from backend.app.config import get_settings
from backend.pipeline.context import PipelineContext

settings = get_settings()


class NoDialogueDetectedError(Exception):
    """Raised when DialogueDetecting.process() returns False — matches main.py's
    early `return` but as an explicit exception so the orchestrator can record it as a
    clear failure reason rather than silently stopping."""


class FileValidationError(Exception):
    """Raised when the uploaded file isn't decodable audio — caught early (stage 1 of
    the required pipeline decomposition) so a corrupted/mislabeled file fails with a
    clear message here instead of a confusing crash deep inside ffprobe/librosa later."""


# Below this, a stereo recording is treated as two independent per-speaker channels
# (agent/client each on their own track) rather than a single mixed-down source — a
# very common telephony recording format, and a much more reliable speaker split than
# statistical diarization when it's actually how the file was recorded. This is a
# heuristic threshold (Pearson correlation between channels over a sample window), not
# a certainty — see Call.is_separate_channel_recording's docstring. NOTE: detection is
# implemented and recorded on the Call row now; the pipeline does not yet branch its
# processing path on this signal (diarization still always runs on the mono-folded
# mix) — see docs/project/AUDIO_PIPELINE.md for why that's a documented follow-up
# rather than done in this pass.
_SEPARATE_CHANNEL_CORRELATION_THRESHOLD = 0.6
_CHANNEL_INSPECTION_SAMPLE_SECONDS = 60


async def step_file_validation(ctx: PipelineContext) -> None:
    """Stage 1: confirm the uploaded file is genuinely decodable audio with a sane
    duration before anything else touches it. Extension checking already happens at
    upload time (backend/app/services/call_service.py) — this is the real content
    check that catches a corrupted file or one that was mislabeled with an audio
    extension."""
    import soundfile as sf

    try:
        info = sf.info(ctx.original_audio_path)
    except Exception as exc:  # noqa: BLE001 — any decode failure means "not valid audio"
        raise FileValidationError(
            f"File is not readable as audio ({type(exc).__name__}: {exc})."
        ) from None

    if info.frames <= 0 or info.samplerate <= 0:
        raise FileValidationError("Audio file contains no samples.")

    duration_seconds = info.frames / info.samplerate
    if duration_seconds < 0.5:
        raise FileValidationError(
            f"Audio is too short to contain a call ({duration_seconds:.2f}s)."
        )

    ctx.call.duration_seconds = duration_seconds


async def step_channel_inspection(ctx: PipelineContext) -> None:
    """Stage 4: record channel layout before anything folds the audio to mono. Reads
    only a bounded sample window (not the whole file) so this stays cheap even for long
    calls."""
    import numpy as np
    import soundfile as sf

    info = sf.info(ctx.original_audio_path)
    ctx.channel_count = info.channels
    ctx.call.channel_count = info.channels

    if info.channels < 2:
        ctx.is_separate_channel_recording = False
        ctx.call.is_separate_channel_recording = False
        return

    sample_frames = min(info.frames, int(_CHANNEL_INSPECTION_SAMPLE_SECONDS * info.samplerate))
    data, _ = sf.read(ctx.original_audio_path, frames=sample_frames, dtype="float32", always_2d=True)

    left, right = data[:, 0], data[:, 1]
    if np.std(left) == 0 or np.std(right) == 0:
        # One channel is silent/constant — correlation is undefined; treat as
        # "not confidently a separate-channel recording" rather than guessing.
        is_separate = False
    else:
        correlation = float(np.corrcoef(left, right)[0, 1])
        is_separate = correlation < _SEPARATE_CHANNEL_CORRELATION_THRESHOLD

    ctx.is_separate_channel_recording = is_separate
    ctx.call.is_separate_channel_recording = is_separate


async def step_dialogue_detection(ctx: PipelineContext) -> None:
    from src.audio.error import DialogueDetecting

    # delete_original left at the class default (False) — main.py hardcoded True here,
    # which is exactly the audit-flagged behavior we do not carry over: the permanently
    # stored recording must survive even when no dialogue is detected.
    detector = DialogueDetecting(temp_dir=ctx.temp_dir)
    has_dialogue = detector.process(ctx.original_audio_path)
    if not has_dialogue:
        raise NoDialogueDetectedError("No dialogue detected in this recording.")


async def step_speech_enhancement(ctx: PipelineContext) -> None:
    from src.audio.preprocessing import SpeechEnhancement

    enhancer = SpeechEnhancement(config_path=settings.pipeline_config_path, output_dir=ctx.temp_dir)
    ctx.enhanced_audio_path = enhancer.enhance_audio(
        input_path=ctx.original_audio_path,
        output_path=os.path.join(ctx.temp_dir, "enhanced.wav"),
        noise_threshold=0.0001,
    )
    ctx.model_versions["speech_enhancement"] = enhancer.model_name
    ctx.call.model_versions = dict(ctx.model_versions)


async def step_vocal_separation(ctx: PipelineContext) -> None:
    from src.audio.effect import DemucsVocalSeparator

    separator = DemucsVocalSeparator()
    ctx.vocal_audio_path = separator.separate_vocals(
        audio_file=ctx.enhanced_audio_path, output_dir=ctx.temp_dir
    ) or ctx.enhanced_audio_path


_WHISPER_MODEL_NAME = "large-v3"


async def step_transcription(ctx: PipelineContext) -> None:
    from src.audio.processing import Transcriber

    pipeline_config = OmegaConf.load(settings.pipeline_config_path)
    transcriber = Transcriber(
        model_name=_WHISPER_MODEL_NAME,
        device=pipeline_config.runtime.device,
        compute_type=pipeline_config.runtime.compute_type,
    )
    transcript, info = transcriber.transcribe(audio_path=ctx.vocal_audio_path)
    ctx.transcript = transcript
    ctx.detected_language = info["language"]
    ctx.call.detected_language = ctx.detected_language
    ctx.model_versions["whisper"] = _WHISPER_MODEL_NAME
    ctx.call.model_versions = dict(ctx.model_versions)


async def step_forced_alignment(ctx: PipelineContext) -> None:
    from src.audio.alignment import ForcedAligner

    pipeline_config = OmegaConf.load(settings.pipeline_config_path)
    aligner = ForcedAligner(device=pipeline_config.runtime.device)
    ctx.word_timestamps = aligner.align(
        audio_path=ctx.vocal_audio_path, transcript=ctx.transcript, language=ctx.detected_language
    )
    # ctc_forced_aligner doesn't expose a configurable/queryable model name (it loads
    # its own default internally) — recorded as a fixed label so at least *that* a
    # forced-alignment pass happened is auditable, even without a specific version string.
    ctx.model_versions["alignment"] = "ctc_forced_aligner_default"
    ctx.call.model_versions = dict(ctx.model_versions)


async def step_diarization(ctx: PipelineContext) -> None:
    from nemo.collections.asr.models.msdd_models import NeuralDiarizer

    from src.audio.processing import AudioProcessor

    processor = AudioProcessor(audio_path=ctx.vocal_audio_path, temp_dir=ctx.temp_dir)
    ctx.mono_audio_path = processor.convert_to_mono()
    processor.audio_path = ctx.mono_audio_path
    manifest_path = os.path.join(ctx.temp_dir, "manifest.json")
    processor.create_manifest(manifest_path)

    diarizer_cfg = OmegaConf.load(settings.pipeline_nemo_config_path)
    diarizer_cfg.diarizer.manifest_filepath = manifest_path
    diarizer_cfg.diarizer.out_dir = ctx.temp_dir
    NeuralDiarizer(cfg=diarizer_cfg).diarize()

    ctx.rttm_path = os.path.join(ctx.temp_dir, "pred_rttms", "mono_file.rttm")
    ctx.model_versions["diarization"] = str(diarizer_cfg.diarizer.msdd_model.model_path)
    ctx.call.model_versions = dict(ctx.model_versions)

    # KNOWN LIMITATION (documented, not silently glossed over — see
    # docs/project/AUDIO_PIPELINE.md "Overlapping speech"): diar_infer_telephonic.yaml
    # sets diarizer.ignore_overlap=True, so overlapping speech is assigned to a single
    # speaker rather than flagged. Not changed here — the downstream WordSpeakerMapper
    # (unmodified, per the approved plan) assumes one speaker per time span and would
    # need its own rework to consume multi-speaker overlap regions correctly.


async def step_speaker_timestamps(ctx: PipelineContext) -> None:
    from src.audio.io import SpeakerTimestampReader

    reader = SpeakerTimestampReader(rttm_path=ctx.rttm_path)
    ctx.speaker_timestamps = reader.read_speaker_timestamps()


async def step_word_speaker_mapping(ctx: PipelineContext) -> None:
    from src.audio.analysis import WordSpeakerMapper

    mapper = WordSpeakerMapper(ctx.word_timestamps, ctx.speaker_timestamps)
    ctx.word_speaker_mapping = mapper.get_words_speaker_mapping()
    ctx._word_speaker_mapper = mapper  # kept for the realign step below


async def step_punctuation_restoration(ctx: PipelineContext) -> None:
    from src.audio.processing import PunctuationRestorer

    restorer = PunctuationRestorer(language=ctx.detected_language)
    wsm = restorer.restore_punctuation(ctx.word_speaker_mapping)

    mapper = getattr(ctx, "_word_speaker_mapper", None)
    if mapper is None:
        from src.audio.analysis import WordSpeakerMapper

        mapper = WordSpeakerMapper(ctx.word_timestamps, ctx.speaker_timestamps)
    mapper.word_speaker_mapping = wsm
    mapper.realign_with_punctuation()
    ctx.word_speaker_mapping = mapper.word_speaker_mapping


async def step_sentence_speaker_mapping(ctx: PipelineContext) -> None:
    from src.audio.analysis import SentenceSpeakerMapper

    ctx.sentence_speaker_mapping = SentenceSpeakerMapper().get_sentences_speaker_mapping(
        ctx.word_speaker_mapping
    )


async def step_export_transcript(ctx: PipelineContext) -> None:
    """Writes .txt/.srt into the call's .temp working dir for operator debugging only —
    the durable transcript is the utterances table, not these files (which are cleaned
    up at the end of the run, see orchestrator.py)."""
    from src.audio.io import TranscriptWriter

    TranscriptWriter.write_transcript(
        ctx.sentence_speaker_mapping, os.path.join(ctx.temp_dir, "output.txt")
    )
    TranscriptWriter.write_srt(
        ctx.sentence_speaker_mapping, os.path.join(ctx.temp_dir, "output.srt")
    )


def _classification_result_is_valid(llm_result, known_speakers: set[str]) -> bool:
    """Independently re-derives LLMResultHandler.validate_and_fallback()'s own validity
    check (src/text/llm.py, unmodified) — same criteria, read-only, so we can tell
    *after the fact* whether the real classification was used or it silently fell back,
    without needing that private method to report it itself. This is what
    Speaker.role_confidence is actually derived from (see that field's docstring)."""
    import re

    if not isinstance(llm_result, dict):
        return False
    if "Customer" not in llm_result or "CSR" not in llm_result:
        return False
    customer_speaker, csr_speaker = llm_result["Customer"], llm_result["CSR"]
    pattern = r"^Speaker\s+\d+$"
    if not (isinstance(customer_speaker, str) and re.match(pattern, customer_speaker)):
        return False
    if not (isinstance(csr_speaker, str) and re.match(pattern, csr_speaker)):
        return False
    return customer_speaker in known_speakers and csr_speaker in known_speakers


async def step_classify_speaker_roles(ctx: PipelineContext) -> None:
    from src.text.llm import LLMOrchestrator, LLMResultHandler

    llm = LLMOrchestrator(
        config_path=settings.pipeline_config_path,
        prompt_config_path=settings.pipeline_prompt_path,
        model_id=settings.llm_provider,
    )
    ctx.speaker_roles_raw = await llm.generate("Classification", ctx.sentence_speaker_mapping)

    known_speakers = {item["speaker"] for item in ctx.sentence_speaker_mapping}
    ctx.role_assignment_used_fallback = not _classification_result_is_valid(
        ctx.speaker_roles_raw, known_speakers
    )

    # LLMResultHandler is left unmodified: its validate_and_fallback()/​_fallback() logic
    # hardcodes the "Customer"/"CSR" literal keys/labels. Rather than edit that class (or
    # the Classification prompt contract it depends on), those two labels are treated as
    # opaque intermediate tags here and translated onto our extensible speaker_roles
    # taxonomy ("client"/"agent") only at persistence time in orchestrator.py — the
    # generalized role model lives in the DB schema, not by touching this class.
    ctx.sentence_speaker_mapping = LLMResultHandler().validate_and_fallback(
        ctx.speaker_roles_raw, ctx.sentence_speaker_mapping
    )

    ctx.model_versions["llm_provider"] = settings.llm_provider
    ctx.call.model_versions = dict(ctx.model_versions)


async def step_sentiment_analysis(ctx: PipelineContext) -> None:
    from src.text.llm import LLMOrchestrator

    llm = LLMOrchestrator(
        config_path=settings.pipeline_config_path,
        prompt_config_path=settings.pipeline_prompt_path,
        model_id=settings.llm_provider,
    )
    ctx.sentiment_results = await llm.generate(
        "SentimentAnalysis", user_input=ctx.sentence_speaker_mapping
    )


async def step_profanity_detection(ctx: PipelineContext) -> None:
    from src.text.llm import LLMOrchestrator

    llm = LLMOrchestrator(
        config_path=settings.pipeline_config_path,
        prompt_config_path=settings.pipeline_prompt_path,
        model_id=settings.llm_provider,
    )
    ctx.profanity_results = await llm.generate(
        "ProfanityWordDetection", user_input=ctx.sentence_speaker_mapping
    )


async def step_summary(ctx: PipelineContext) -> None:
    from src.text.llm import LLMOrchestrator

    llm = LLMOrchestrator(
        config_path=settings.pipeline_config_path,
        prompt_config_path=settings.pipeline_prompt_path,
        model_id=settings.llm_provider,
    )
    ctx.summary_result = await llm.generate("Summary", user_input=ctx.sentence_speaker_mapping)


async def step_conflict_detection(ctx: PipelineContext) -> None:
    from src.text.llm import LLMOrchestrator

    llm = LLMOrchestrator(
        config_path=settings.pipeline_config_path,
        prompt_config_path=settings.pipeline_prompt_path,
        model_id=settings.llm_provider,
    )
    ctx.conflict_result = await llm.generate(
        "ConflictDetection", user_input=ctx.sentence_speaker_mapping
    )


async def step_topic_detection(ctx: PipelineContext) -> None:
    from sqlalchemy import select

    from src.text.llm import LLMOrchestrator

    from backend.app.models.qa import Scorecard  # noqa: F401 (reserved for future topic-per-project scoping)

    llm = LLMOrchestrator(
        config_path=settings.pipeline_config_path,
        prompt_config_path=settings.pipeline_prompt_path,
        model_id=settings.llm_provider,
    )
    # Phase 1: no persisted Topic table (superseded by the versioned scorecard/QA-engine
    # design) — pass an empty known-topics list; the LLM proposes a new topic freely.
    ctx.topic_result = await llm.generate(
        "TopicDetection", user_input=ctx.sentence_speaker_mapping, system_input=[]
    )


async def step_acoustic_metrics(ctx: PipelineContext) -> None:
    from src.audio.analysis import Audio

    # Computed on the ORIGINAL permanently-stored recording, matching the existing
    # pipeline's behavior (main.py's Audio() is constructed on audio_file_path, not the
    # enhanced/vocals-only derivative) — recorded explicitly, not left implicit, via
    # acoustic_metrics.source_audio_variant = 'original'.
    ctx.acoustic_properties = Audio(ctx.original_audio_path).properties()


async def step_silence_metrics(ctx: PipelineContext) -> None:
    from src.audio.metrics import SilenceStats

    stats = SilenceStats.from_segments(ctx.sentence_speaker_mapping)
    ctx.silence_threshold = stats.threshold_std(factor=0.99)

    # New metrics (not present in the original pipeline) needed by speaker-behavior QA
    # rule types — computed here rather than added to SilenceStats/Audio to avoid
    # touching those unmodified classes.
    segments = sorted(ctx.sentence_speaker_mapping, key=lambda s: s["start_time"])
    interruptions = 0
    for prev, nxt in zip(segments, segments[1:]):
        if nxt["speaker"] != prev["speaker"] and nxt["start_time"] < prev["end_time"]:
            interruptions += 1
    ctx.interruption_count = interruptions

    total_duration = sum(s["end_time"] - s["start_time"] for s in segments) or 1
    agent_duration = sum(
        s["end_time"] - s["start_time"] for s in segments if s["speaker"] == "CSR"
    )
    ctx.agent_talk_ratio = agent_duration / total_duration
