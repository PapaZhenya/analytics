# Callytics — полный пайплайн: от аудио до результата

Источник истины — `main.py`, функция `async def main(audio_file_path)`, шаги 1–18
(комментарии `# Step N` в самом коде). Ниже — схема верхнего уровня и детальный разбор
каждого шага: какие классы задействованы, что на входе, что на выходе, какие файлы на диске
создаются/читаются.

## 1. Схема верхнего уровня

```
Audio (входной файл в .data/input, подхватывается watchdog.Observer)
↓
Dialogue Detection (pyannote, чанки по 5с) — ранний gate: если диалога нет → СТОП,
                                              исходный файл может быть удалён
↓
Speech Enhancement (MPSENet) — шумоподавление/улучшение речи
↓
Voice Separation (Demucs htdemucs, two_stems=vocals) — отделение вокала от фона
↓
Whisper (faster-whisper large-v3) — транскрипция речи в текст
↓
Forced Alignment (ctc_forced_aligner) — привязка каждого слова к точному времени
↓
Speaker Diarization (NeMo NeuralDiarizer / MSDD, telephonic-конфиг) — "кто говорил когда" (RTTM)
↓
Speaker Mapping (WordSpeakerMapper → PunctuationRestorer → realign → SentenceSpeakerMapper)
      — слова + время + спикер → предложения + спикер (ssm)
↓
Export (TranscriptWriter) — необязательный сброс .txt / .srt на диск
↓
LLM-анализ (LLMOrchestrator, 6 последовательных задач над ssm):
   Classification → LLMResultHandler (нормализация ролей Customer/CSR)
   → SentimentAnalysis → ProfanityWordDetection → Summary → ConflictDetection → TopicDetection
↓
Metrics: Audio.properties() (акустика по исходному файлу) + SilenceStats (тишина по ssm)
↓
Database (SQLite): INSERT в File (метаданные+акустика+summary+conflict+silence),
                    затем INSERT в Utterance (по одной строке на реплику ssm)
↓
Clean Up (Cleaner) — удаление .temp/ и исходного аудиофайла
```

## 2. Пошаговый разбор (main.py)

### Инициализация (до Шага 1)

Конфиги грузятся через `OmegaConf.load(config_path)` (`config/config.yaml`); из него берутся
`runtime.device`, `runtime.compute_type`, `runtime.cuda_alloc_conf` (последнее пишется в
`os.environ["PYTORCH_CUDA_ALLOC_CONF"]`). Затем **одновременно** создаются экземпляры всех
классов пайплайна (тяжёлая инициализация: загрузка моделей MPSENet, faster-whisper, aligner —
происходит здесь, а не лениво):

```python
dialogue_detector = DialogueDetecting(delete_original=True)
enhancer = SpeechEnhancement(config_path=config_path, output_dir=temp_dir)
separator = DemucsVocalSeparator()
processor = AudioProcessor(audio_path=audio_file_path, temp_dir=temp_dir)
transcriber = Transcriber(device=device, compute_type=compute_type)
aligner = ForcedAligner(device=device)
llm_handler = LLMOrchestrator(config_path=config_path, prompt_config_path=prompt_path, model_id="openai")
llm_result_handler = LLMResultHandler()
cleaner = Cleaner()
formatter = Formatter()
db = Database(db_path)
audio_feature_extractor = Audio(audio_file_path)
```

Обратите внимание: `model_id="openai"` захардкожен в вызове `main()` — переключение на
`"llama"`/`"azure_openai"` возможно только правкой кода, не через конфиг/переменную окружения.

### Шаг 1 — Dialogue Detection

- **Класс:** `DialogueDetecting.process(audio_file_path)`
- **Вход:** путь к исходному файлу
- **Логика:** нарезка на 5-секундные чанки через ffmpeg, прогон каждого чанка через
  `pyannote/speaker-diarization`, ранняя остановка при обнаружении ≥2 уникальных спикеров.
- **Выход:** `bool`. Если `False` — `main()` завершается через `return` **до** любой другой
  обработки; если при этом `delete_original=True` (как захардкожено в `main.py`) — исходный
  файл удаляется.

### Шаг 2 — Speech Enhancement

- **Класс:** `SpeechEnhancement.enhance_audio(input_path=audio_file_path, output_path=".temp/enhanced.wav", noise_threshold=0.0001)`
- **Модель:** MPSENet (`config.models.mpsenet.model_name`), запускается на `runtime.device`.
- **Логика:** если RMS-шум ниже порога — модель не запускается, возвращается исходный путь.
- **Выход:** путь к `enhanced.wav` (или исходный путь).

### Шаг 3 — Voice Separation

- **Класс:** `DemucsVocalSeparator.separate_vocals(audio_file=audio_path, output_dir=temp_dir)`
- **Модель:** Demucs `htdemucs`, `two_stems="vocals"`.
- **Выход:** `.temp/htdemucs/{basename}/vocals.wav`; при сбое — fallback на входной файл с
  предупреждением.

### Шаг 4 — Whisper (транскрипция)

- **Класс:** `Transcriber.transcribe(audio_path=vocal_path)`
- **Модель:** `faster_whisper.WhisperModel("large-v3", device=..., compute_type=...)`,
  `vad_filter=True`.
- **Выход:** `(transcript: str, info: dict)`; `info["language"]` определяет язык для
  следующих шагов (alignment, punctuation).

### Шаг 5 — Forced Alignment

- **Класс:** `ForcedAligner.align(audio_path=vocal_path, transcript=transcript, language=detected_language)`
- **Библиотека:** `ctc_forced_aligner` (load_alignment_model → generate_emissions →
  preprocess_text → get_alignments → get_spans → postprocess_results).
- **Выход:** `word_timestamps: List[{"text", "start", "end"}]` — покадровые тайминги слов.

### Шаг 6 — Speaker Diarization

- **Классы:** `AudioProcessor.convert_to_mono()` → `AudioProcessor.create_manifest(manifest_path)`
  → `nemo...NeuralDiarizer(cfg).diarize()`
- **Конфиг:** `config/nemo/diar_infer_telephonic.yaml` (VAD `vad_multilingual_marblenet`,
  embeddings `titanet_large`, clustering до 8 спикеров, MSDD `diar_msdd_telephonic`).
- **Вход:** моно-версия вокального трека + JSON-манифест
  (`{"audio_filepath", "offset":0, "duration", "label":"infer", "text":"-", "rttm_filepath":None, "uem_filepath":None}`).
- **Выход:** RTTM-файл на диске: `.temp/pred_rttms/mono_file.rttm` (не возвращается как
  значение — читается на следующем шаге через файловую систему).

### Шаг 7 — Обработка транскрипта (4 под-шага)

**7.1 —** `SpeakerTimestampReader(rttm_file_path).read_speaker_timestamps()` →
`speaker_ts: List[[start_ms, end_ms, speaker_id:int]]` (парсинг RTTM, невалидные строки
пропускаются).

**7.2 —** `WordSpeakerMapper(word_timestamps, speaker_ts).get_words_speaker_mapping()` →
`wsm: List[{"text","start_time","end_time","speaker"}]` — каждому слову присваивается спикер
по правилу "чей интервал перекрывает якорную точку слова (start/mid/end)".

**7.3 —** `PunctuationRestorer(language=detected_language).restore_punctuation(wsm)` (модель
`kredor/punctuate-all`) → пунктуация добавлена в текст слов; затем
`word_speaker_mapper.realign_with_punctuation()` — сглаживает границы спикеров внутри одного
предложения (если начало/конец предложения не совпадает со сменой спикера, большинство слов
предложения "перетягивают" спикера).

**7.4 —** `SentenceSpeakerMapper().get_sentences_speaker_mapping(wsm)` (NLTK
`PunktSentenceTokenizer`) → **`ssm`** — центральная структура данных всего оставшегося
пайплайна: `List[{"speaker","start_time","end_time","text"}]`.

### Шаг 8 — Export (опционально)

- **Класс:** `TranscriptWriter`
- `write_transcript(ssm, ".temp/output.txt")` — плоский текст, сгруппированный по спикеру.
- `write_srt(ssm, ".temp/output.srt")` — субтитры с таймкодами `HH:MM:SS,mmm`.
- Оба файла позже удаляются на Шаге 18 (`Cleaner.cleanup(temp_dir, ...)`), если их не забрать
  до завершения обработки.

### Шаги 9–14 — LLM-анализ

Все используют один и тот же `LLMOrchestrator.generate(prompt_name, user_input=ssm[, system_input])`,
который: 1) берёт system/user шаблоны из `config/prompt.yaml`; 2) форматирует ssm в диалог через
`Formatter.format_ssm_as_dialogue()`; 3) вызывает `LanguageModelManager.generate(model_id="openai", messages, max_new_tokens=10000)`;
4) вытаскивает последний валидный JSON-объект регуляркой из ответа модели.

| Шаг | Задача (`prompt_name`) | Что делает | Куда пишется результат |
|---|---|---|---|
| 9 | `Classification` | Определяет, какой `"Speaker N"` — Customer, какой — CSR | `llm_result_handler.validate_and_fallback()` — переписывает `ssm[i]["speaker"]` в `"Customer"`/`"CSR"` (либо fallback: первый спикер = CSR, если LLM вернул некорректный формат) |
| 10 | `SentimentAnalysis` | Тональность каждой реплики (Positive/Negative/Neutral) | `Annotator.add_sentiment()` → `ssm[i]["sentiment"]` |
| 11 | `ProfanityWordDetection` | Наличие ненормативной лексики по репликам | `Annotator.add_profanity()` → `ssm[i]["profane"]` |
| 12 | `Summary` | Одно предложение — краткое содержание звонка | `Annotator.add_summary()` → `global_summary` |
| 13 | `ConflictDetection` | Был ли конфликт/несогласие в разговоре | `Annotator.add_conflict()` → `global_conflict` |
| 14 | `TopicDetection` | Тема звонка (сверяется со списком существующих тем из БД, `db.fetch(TopicFetch.sql)`) | `Annotator.add_topic()` → `global_topic` |

После Шага 9 добавляются индексы: `Formatter.add_indices_to_ssm(ssm)` → `ssm_with_indices`,
на основе которых создаётся `Annotator(ssm_with_indices)`.

### Шаг 15 — Акустические метрики файла

- **Класс:** `audio_feature_extractor.properties()` (экземпляр `Audio`, созданный в самом
  начале `main()` **на исходном** `audio_file_path`, а не на enhanced/vocal-версии).
- **Выход:** имя файла, расширение, абсолютный путь, sample rate, min/max частота, битность,
  каналы, длительность, RMS loudness, словарь `final_features` (4 EQ-полосы, ZCR, spectral
  centroid, 13 MFCC).

### Шаг 16 — Тишина

- **Класс:** `SilenceStats.from_segments(final_output["ssm"]).threshold_std(factor=0.99)`
- Считает промежутки между репликами (`start_time[i+1] - end_time[i]`), берёт `std()` этих
  промежутков × 0.99 как порог, сохраняет в `final_output["silence"]`.

### Шаг 17 — Запись в БД

**17.1 —** `db.get_or_insert_topic_id(detected_topic, topics, TopicInsert.sql)` → `topic_id`;
затем `db.insert(AudioPropertiesInsert.sql, params)` с 33 позиционными параметрами (имя,
topic_id, расширение, путь, sample rate, min/max freq, bit depth, channels, duration, RMS,
ZCR, spectral centroid, 4×EQ, 13×MFCC, summary, conflict flag, silence) → `last_id` (это
`File.ID`).

**17.2 —** Цикл по `final_output["ssm"]`: для каждой реплики
`db.insert(UtteranceInsert.sql, (file_id, speaker, sequence, start_time/1000, end_time/1000, content, sentiment, profane))`.

### Шаг 18 — Очистка

- **Класс:** `Cleaner.cleanup(temp_dir, audio_file_path)` — удаляет **весь `.temp/`** (включая
  `output.txt`/`output.srt`/RTTM/манифест/enhanced/vocals) **и исходный входной аудиофайл**.
  После этого шага на диске не остаётся ни аудио, ни промежуточных артефактов — только строки
  в SQLite.

## 3. Эволюция формы данных сквозь пайплайн

```
bytes аудиофайла
  → bool (есть диалог?)                                    [Шаг 1]
  → путь к .wav (enhanced)                                 [Шаг 2]
  → путь к .wav (vocals-only)                              [Шаг 3]
  → (str transcript, dict info)                            [Шаг 4]
  → List[{text,start,end}]  (word_timestamps)              [Шаг 5]
  → файл .rttm на диске                                    [Шаг 6]
  → List[[start_ms,end_ms,speaker_id]]  (speaker_ts)        [Шаг 7.1]
  → List[{text,start_time,end_time,speaker}]  (wsm)         [Шаг 7.2-7.3]
  → List[{speaker,start_time,end_time,text}]  (ssm)          [Шаг 7.4]  ← ключевая структура
  → ssm с speaker ∈ {"Customer","CSR"}                       [Шаг 9]
  → ssm[i]["sentiment"], ssm[i]["profane"]                   [Шаги 10-11]
  → dict {ssm, summary, conflict, topic}  (final_output)     [Шаги 12-14, через Annotator.finalize()]
  → final_output + final_output["silence"]                   [Шаг 16]
  → строка в таблице File + N строк в таблице Utterance      [Шаг 17]
```
