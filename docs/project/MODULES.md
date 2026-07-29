# Callytics — разбор по функциональным модулям

Ниже — назначение каждого запрошенного модуля, с точной привязкой к файлам/классам/моделям
и известными ограничениями, обнаруженными при чтении кода.

## Speech Enhancement

- **Файл/класс:** `src/audio/preprocessing.py::SpeechEnhancement`
- **Модель:** MPSENet (HuggingFace, имя берётся из `config/config.yaml → models.mpsenet.model_name`,
  по умолчанию `JacobLinCool/MP-SENet-DNS`).
- **Назначение:** убрать шум/улучшить разборчивость речи ДО транскрипции и диаризации.
  Если RMS-уровень шума ниже `noise_threshold` (в `main.py` = `0.0001`) — модель не
  запускается, файл проходит без изменений (оптимизация, чтобы не тратить GPU/CPU на уже
  чистый звук).
- **Место в пайплайне:** Шаг 2, сразу после подтверждения диалога, до Demucs.
- **Ограничение:** есть "сосед"-класс `Denoiser` (librosa+noisereduce) в том же файле, который
  делает похожую задачу, но **не используется** — в проекте фактически один активный путь
  шумоподавления (MPSENet), второй — мёртвый код.

## Voice Separation

- **Файл/класс:** `src/audio/effect.py::DemucsVocalSeparator`
- **Модель:** Demucs, `model_name="htdemucs"`, `two_stems="vocals"` (разделяет запись на
  "вокал" и "всё остальное", берёт только вокал).
- **Назначение:** убрать фоновую музыку/шум окружения, оставить только голоса — критично для
  телефонных записей с плохим качеством линии или колл-центров с фоновым шумом.
- **Место в пайплайне:** Шаг 3, между Speech Enhancement и Whisper.
- **Ограничение:** при любой ошибке разделения — тихий fallback на исходный файл с
  `print`-предупреждением (не исключение, не лог уровня ERROR) — сбой легко пропустить в
  продакшене.

## Whisper

- **Файл/класс:** `src/audio/processing.py::Transcriber`
- **Модель:** `faster_whisper.WhisperModel("large-v3")`, `vad_filter=True` (использует
  встроенный Silero VAD faster-whisper для отсечения тишины перед транскрипцией).
- **Назначение:** речь → текст (транскрипт) + определение языка (`info["language"]"`), которое
  затем передаётся в `ForcedAligner` и `PunctuationRestorer`.
- **Место в пайплайне:** Шаг 4, работает на вокальном треке после Demucs (не на исходном
  аудио).
- **Ограничение:** опция `suppress_numerals` (подавление токенов с цифрами через
  `TokenizerUtils`) реализована, но `main.py` её не передаёт — фича написана, но не
  используется в реальном пайплайне.

## Alignment

- **Файл/класс:** `src/audio/alignment.py::ForcedAligner`
- **Библиотека:** `ctc_forced_aligner` (git-зависимость, не PyPI-релиз).
- **Назначение:** привязать каждое слово транскрипта к точным временным меткам (start/end в
  секундах) — Whisper даёт текст, но недостаточно точные тайминги по словам; forced alignment
  восстанавливает точность через CTC-эмиссии акустической модели.
- **Место в пайплайне:** Шаг 5, результат (`word_timestamps`) используется на Шаге 7.2 для
  сопоставления слов со спикерами.
- **Ограничение:** явно освобождает CUDA-память после работы (`torch.cuda.empty_cache()`),
  но других classов пайплайна с явным освобождением GPU-памяти немного — управление памятью
  несистемное (кэш моделей в `LanguageModelManager` — единственное место с явной политикой
  вытеснения).

## Speaker Diarization

- **Файлы:** `main.py` (Шаг 6, напрямую использует `nemo.collections.asr.models.msdd_models.NeuralDiarizer`),
  конфиг `config/nemo/diar_infer_telephonic.yaml`.
- **Модели:** VAD `vad_multilingual_marblenet`, speaker embeddings `titanet_large`
  (мультимасштабные окна 1.5/1.25/1.0/0.75/0.5 с), кластеризация (до `max_num_speakers: 8`),
  MSDD-модель `diar_msdd_telephonic` (специально обучена под телефонные звонки, 8kHz-подобный
  профиль звука).
- **Назначение:** определить "кто говорил в какой момент времени" независимо от содержания
  речи — на выходе RTTM-файл (`start_time duration ... speaker_label`).
- **Место в пайплайне:** Шаг 6, работает на **моно**-версии вокального трека (не оригинал, не
  стерео).
- **Ограничение:** пайплайн НЕ читает возвращаемое значение `msdd_model.diarize()` напрямую —
  результат передаётся исключительно через файл на диске
  (`.temp/pred_rttms/mono_file.rttm`), который затем читает `SpeakerTimestampReader`. Жёсткая
  зависимость от конкретного имени файла NeMo (`mono_file.rttm`) — если NeMo изменит схему
  именования выходных файлов, пайплайн сломается без явной ошибки на этом шаге.

## Speaker Mapping

- **Файл/классы:** `src/audio/analysis.py::WordSpeakerMapper`, `SentenceSpeakerMapper`
- **Назначение:** соединить два независимых источника — тайминги слов (Whisper+alignment) и
  тайминги спикеров (диаризация) — в единую структуру "кто что сказал".
  - `WordSpeakerMapper.get_words_speaker_mapping()` — на уровне слов, по правилу "якорная точка
    слова (start/mid/end) попадает в интервал спикера".
  - `WordSpeakerMapper.realign_with_punctuation()` — после восстановления пунктуации
    сглаживает "дребезг" спикера внутри одного предложения (мажоритарное голосование по словам
    предложения).
  - `SentenceSpeakerMapper.get_sentences_speaker_mapping()` — группирует слова в предложения
    (NLTK `PunktSentenceTokenizer.text_contains_sentbreak`) с учётом смены спикера.
- **Место в пайплайне:** Шаги 7.2–7.4, между диаризацией/alignment и LLM-анализом.
- **Результат:** `ssm` (sentence-speaker-mapping) — главная структура данных, вокруг которой
  строится весь дальнейший пайплайн (LLM-анализ, метрики, экспорт, запись в БД).

## LLM

- **Файлы:** `src/text/llm.py` (`LLMOrchestrator`, `LLMResultHandler`), `src/text/model.py`
  (`LanguageModel`/`LLaMAModel`/`OpenAIModel`/`AzureOpenAIModel`/`ModelRegistry`/`ModelFactory`/
  `LanguageModelManager`), `config/prompt.yaml`.
- **Назначение:** 6 последовательных задач анализа диалога — Classification (роли спикеров),
  SentimentAnalysis, ProfanityWordDetection, Summary, ConflictDetection, TopicDetection.
  Архитектурно — паттерн Registry/Factory: `model_id` (`"llama"`/`"openai"`/`"azure_openai"`)
  определяет, какой класс создать; `LanguageModelManager` кэширует до `cache_size` моделей с
  LRU-вытеснением (`OrderedDict`).
- **Место в пайплайне:** Шаги 9–14, `model_id="openai"` захардкожен в `main.py`.
- **Ограничения:**
  - `AzureOpenAIModel` использует устаревший **pre-1.0 openai SDK API**
    (`openai.ChatCompletion.create`, `openai.api_type = "azure"`), несовместимый с закреплённой
    версией `openai==1.57.0` — при выборе `model_id="azure_openai"` ожидается `AttributeError`.
  - Формат ответа LLM извлекается регуляркой (`extract_json`) из свободного текста — нет
    гарантированного structured output (не используется `response_format={"type":"json_object"}`
    в вызовах, хотя `OpenAIModel.generate()` поддерживает такой параметр как `return_as_json`,
    но `LLMOrchestrator` его не передаёт).
  - Промпты (`config/prompt.yaml`) жёстко привязаны к сценарию "звонок в контакт-центр":
    ролевая модель ограничена двумя ролями — `Customer`/`CSR`.
  - `PromptManager` (`src/text/prompt.py`) — параллельный, не используемый механизм загрузки
    промптов; создаёт риск путаницы, какой из двух путей загрузки промптов "настоящий".

## Database

- **Файлы:** `src/db/manager.py::Database`, `src/db/sql/*.sql`
- **СУБД:** SQLite (`.db/Callytics.sqlite`), доступ через стандартный `sqlite3`, без ORM.
- **Схема:** `Topic(ID, Name)`, `File(... 30+ акустических/LLM-полей ...)`,
  `Utterance(ID, FileID, Speaker, Sequence, StartTime, EndTime, Content, Sentiment, Profane)`.
- **Назначение:** финальное хранилище результатов обработки — раз в звонок одна строка `File`
  + N строк `Utterance`.
- **Место в пайплайне:** Шаг 17 (после LLM-анализа и метрик, перед очисткой).
- **Ограничения:**
  - Нет миграционного механизма — `Schema.sql` нужно применять вручную, версионирования схемы
    нет.
  - `Utterance.Speaker` жёстко ограничен `CHECK (Speaker IN ('Customer', 'CSR'))` —
    несовместимо с многосторонними разговорами (диаризация поддерживает до 8 спикеров).
  - SQL-запросы читаются из файлов на каждый вызов (`open(sql_file_path)` при каждом
    `fetch`/`insert`) — постоянный disk I/O вместо кэширования текста запроса в памяти.
  - Каждый `fetch`/`insert` открывает и закрывает новое соединение `sqlite3.connect()` —
    нет пула соединений (для SQLite это не критично, но исключает WAL-оптимизации при
    конкурентных обращениях).

## Export

- **Файл/класс:** `src/audio/io.py::TranscriptWriter`
- **Назначение:** необязательный человекочитаемый вывод диалога — `.txt` (сплошной текст,
  сгруппированный по репликам одного спикера подряд) и `.srt` (субтитры с таймкодами).
- **Место в пайплайне:** Шаг 8, сразу после получения `ssm`, до LLM-анализа.
- **Ограничение:** оба файла пишутся в `.temp/` и **удаляются на Шаге 18**
  (`Cleaner.cleanup(temp_dir, ...)`), если их не скопировать в постоянное хранилище до конца
  обработки — то есть по факту экспорт сейчас работает только "на лету" в рамках одного
  запуска, а не как постоянный артефакт.

## Metrics

Модуль фактически состоит из двух независимых частей:

1. **Акустические характеристики файла** — `src/audio/analysis.py::Audio.properties()`.
   RMS loudness, zero-crossing rate, spectral centroid (через `np.fft.rfft`), 4 полосы EQ
   (20-250Hz, 250-2000Hz, 2000-6000Hz, 6000-20000Hz, через полный `scipy.fft.fft`), 13 MFCC
   (`librosa.feature.mfcc`), плюс метаданные (sample rate, bit depth, каналы, длительность).
   Считается на Шаге 15, **по исходному файлу** (`audio_file_path`), а не по
   enhanced/vocals-версии — то есть в признаках присутствует фоновый шум записи.

2. **Статистика тишины** — `src/audio/metrics.py::SilenceStats`. Вычисляет промежутки между
   соседними репликами в `ssm` (`from_segments`), даёт `mean/median/std/iqr` и два варианта
   порога (`threshold_std`, `threshold_median_iqr`), а также сумму тишины выше порога
   (`total_silence_above_threshold`). В `main.py` используется только
   `threshold_std(factor=0.99)`, второй метод (`threshold_median_iqr`) реализован, но нигде не
   вызывается за пределами `if __name__` демо-блока самого файла.

Обе части НЕ пересекаются с "LLM"-метриками (sentiment/conflict/summary/topic) — это чисто
сигнально-статистические вычисления без обращения к языковым моделям.

## Дополнительно: модули, не входящие в исходный список, но необходимые для полноты картины

- **Dialogue Detection** (`src/audio/error.py::DialogueDetecting`) — самый первый шаг
  пайплайна, действует как gate до Speech Enhancement; без него нет ни одной из
  перечисленных выше стадий.
- **Punctuation Restoration** (`src/audio/processing.py::PunctuationRestorer`) — необходимый
  мост между Whisper (текст часто без пунктуации) и Speaker Mapping (realign использует
  пунктуацию для определения границ предложений); без него `realign_with_punctuation()` не
  сработал бы корректно.
