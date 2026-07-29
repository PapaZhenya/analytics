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


async def step_vocal_separation(ctx: PipelineContext) -> None:
    from src.audio.effect import DemucsVocalSeparator

    separator = DemucsVocalSeparator()
    ctx.vocal_audio_path = separator.separate_vocals(
        audio_file=ctx.enhanced_audio_path, output_dir=ctx.temp_dir
    ) or ctx.enhanced_audio_path


async def step_transcription(ctx: PipelineContext) -> None:
    from src.audio.processing import Transcriber

    pipeline_config = OmegaConf.load(settings.pipeline_config_path)
    transcriber = Transcriber(
        device=pipeline_config.runtime.device, compute_type=pipeline_config.runtime.compute_type
    )
    transcript, info = transcriber.transcribe(audio_path=ctx.vocal_audio_path)
    ctx.transcript = transcript
    ctx.detected_language = info["language"]
    ctx.call.detected_language = ctx.detected_language


async def step_forced_alignment(ctx: PipelineContext) -> None:
    from src.audio.alignment import ForcedAligner

    pipeline_config = OmegaConf.load(settings.pipeline_config_path)
    aligner = ForcedAligner(device=pipeline_config.runtime.device)
    ctx.word_timestamps = aligner.align(
        audio_path=ctx.vocal_audio_path, transcript=ctx.transcript, language=ctx.detected_language
    )


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


async def step_classify_speaker_roles(ctx: PipelineContext) -> None:
    from src.text.llm import LLMOrchestrator, LLMResultHandler

    llm = LLMOrchestrator(
        config_path=settings.pipeline_config_path,
        prompt_config_path=settings.pipeline_prompt_path,
        model_id=settings.llm_provider,
    )
    ctx.speaker_roles_raw = await llm.generate("Classification", ctx.sentence_speaker_mapping)
    # LLMResultHandler is left unmodified: its validate_and_fallback()/​_fallback() logic
    # hardcodes the "Customer"/"CSR" literal keys/labels. Rather than edit that class (or
    # the Classification prompt contract it depends on), those two labels are treated as
    # opaque intermediate tags here and translated onto our extensible speaker_roles
    # taxonomy ("client"/"agent") only at persistence time in orchestrator.py — the
    # generalized role model lives in the DB schema, not by touching this class.
    ctx.sentence_speaker_mapping = LLMResultHandler().validate_and_fallback(
        ctx.speaker_roles_raw, ctx.sentence_speaker_mapping
    )


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
