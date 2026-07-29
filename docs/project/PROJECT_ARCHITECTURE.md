# Callytics — архитектурный аудит проекта

> Документ подготовлен как read-only технический аудит репозитория `analytics` (форк Callytics,
> ветка `feature/local-qa-platform`, идентична `develop`, коммитов ещё нет). Никакой код не
> изменялся, зависимости не устанавливались, проект не запускался. Это чистый анализ текущего
> состояния кодовой базы.

## 1. Что такое Callytics сегодня

Callytics — это **не сервис и не платформа**, а один монолитный Python-скрипт (`main.py`),
который:

1. Слушает директорию `.data/input` через `watchdog` (файловый watcher).
2. При появлении нового аудиофайла (`.mp3`, `.wav`, `.flac`) синхронно запускает
   18-шаговый асинхронный пайплайн обработки звонка (`main(audio_file_path)`).
3. Результат работы пайплайна (транскрипт, разметка по спикерам, LLM-аннотации,
   акустические метрики) сохраняется в единственный файл SQLite (`.db/Callytics.sqlite`).

Это **research-prototype / proof-of-concept уровня**, а не production-система:

- Нет тестов (в репозитории нет ни одного `test_*.py`, README прямо указывает "Unit Tests" в
  разделе "Upcoming").
- Нет CI/CD (`.github/` содержит только `CODEOWNERS`, workflow-файлов нет).
- Нет контейнеризации (README также указывает "Dockerization" как будущую задачу).
- Нет API-слоя — единственная точка входа это `if __name__ == "__main__":` в `main.py`,
  запускающая блокирующий watcher.
- Нет очереди задач/конкурентности — файлы обрабатываются строго по одному, синхронно.
- Обработка ошибок практически отсутствует — большинство классов не оборачивают вызовы моделей
  в try/except (кроме `LanguageModelManager.generate`, `DemucsVocalSeparator.separate_vocals`).
- Всё состояние (модели, конфиги) живёт в оперативной памяти одного процесса на одной машине.

## 2. Границы системы (bounded context)

```
┌─────────────────────────────────────────────────────────────────┐
│ Единственный процесс на одной машине (systemd unit callytics)    │
│                                                                   │
│  watchdog.Observer  →  main.process(path)  →  main.main(path)    │
│                                                                   │
│  Все ML-модели (pyannote, MPSENet, Demucs, faster-whisper,       │
│  ctc-forced-aligner, NeMo MSDD, deepmultilingualpunctuation,     │
│  OpenAI/Azure/LLaMA) загружаются в память ОДНОГО процесса и      │
│  живут, пока жив процесс.                                        │
│                                                                   │
│  Персистентность: единственный файл .db/Callytics.sqlite         │
└─────────────────────────────────────────────────────────────────┘
```

Нет разделения на слои (API / worker / storage), нет очереди сообщений, нет горизонтального
масштабирования. Всё — один Python-процесс.

## 3. Полная карта файлов

### 3.1 Точка входа

| Файл | Назначение | Кто вызывает | Использует классы | Зависимости | Вход | Выход |
|---|---|---|---|---|---|---|
| `main.py` | Оркестратор всего пайплайна: `async def main(audio_file_path)` — 18 шагов от аудио до записи в БД; `async def process(path)` — callback для watcher; `if __name__` — запуск `Watcher.start_watcher(".data/input", process)` | Никто (entry point) | `Formatter`, `SilenceStats`, `DialogueDetecting`, `ForcedAligner`, `DemucsVocalSeparator`, `SpeechEnhancement`, `SpeakerTimestampReader`, `TranscriptWriter`, `WordSpeakerMapper`, `SentenceSpeakerMapper`, `Audio`, `AudioProcessor`, `Transcriber`, `PunctuationRestorer`, `Annotator`, `LLMOrchestrator`, `LLMResultHandler`, `Cleaner`, `Watcher`, `Database`, `NeuralDiarizer` (nemo) | `omegaconf`, `nemo_toolkit` + все `src.*` модули | путь к аудиофайлу (str) | ничего не возвращает; побочные эффекты: запись в SQLite, запись `.temp/output.txt`/`.srt`, удаление исходного файла и `.temp` |

### 3.2 `src/audio/` — обработка звука

| Файл | Класс(ы) | Назначение | Кто вызывает | Зависимости | Вход | Выход |
|---|---|---|---|---|---|---|
| `error.py` | `DialogueDetecting` | Ранний "gate": режет аудио на 5-секундные чанки (ffmpeg), прогоняет через `pyannote/speaker-diarization`, останавливается как только найдено ≥2 спикеров → диалог подтверждён | `main.py`, Шаг 1 | `pyannote.audio.Pipeline`, subprocess (ffmpeg/ffprobe) | путь к аудио | `bool` (есть диалог или нет); опционально удаляет исходный файл, если диалога нет и `delete_original=True` |
| `preprocessing.py` | `Denoiser` | Шумоподавление через `librosa` + `noisereduce`, с порогом RMS | **Никто** — не импортируется в `main.py` | `librosa`, `noisereduce`, `src.utils.utils.Logger` | путь к шумному аудио | путь к denoised.wav или исходный путь (если шум ниже порога) |
| `preprocessing.py` | `SpeechEnhancement` | Улучшение речи через модель MPSENet (HuggingFace) | `main.py`, Шаг 2 | `librosa`, `MPSENet`, `config/config.yaml` (`models.mpsenet.model_name`, `runtime.device`) | путь к аудио, порог шума | путь к enhanced.wav или исходный путь |
| `effect.py` | `DemucsVocalSeparator` | Отделение вокала от фона через Demucs (`htdemucs`, `two_stems="vocals"`) | `main.py`, Шаг 3 | `demucs.separate` (subprocess-style вызов Python API) | путь к аудио, выходная директория | путь к `{output_dir}/htdemucs/{name}/vocals.wav`; при ошибке — fallback на исходный файл |
| `processing.py` | `AudioProcessor` | Общие утилиты: конвертация в моно, тримминг, громкость, слияние/разбиение, **`create_manifest()`** — генерация JSON-манифеста для NeMo диаризации | `main.py`, Шаг 6 | `pydub` | путь к аудио | манифест `.temp/manifest.json`, моно-wav |
| `processing.py` | `Transcriber` | Обёртка над `faster_whisper.WhisperModel("large-v3")` — модуль **Whisper** | `main.py`, Шаг 4 | `faster_whisper`, опционально `TokenizerUtils` (только если `suppress_numerals=True`, что `main.py` **не передаёт** — путь не используется в текущем пайплайне) | путь к аудио (вокал после Demucs) | `(transcript: str, info: dict)`, включая `info["language"]` |
| `processing.py` | `PunctuationRestorer` | Восстановление пунктуации через `deepmultilingualpunctuation.PunctuationModel("kredor/punctuate-all")` | `main.py`, Шаг 7.3 | HuggingFace модель `kredor/punctuate-all` | список word-mapping словарей | тот же список с расставленными `.`, `?`, `!` |
| `alignment.py` | `ForcedAligner` | Принудительное выравнивание слов по времени через `ctc_forced_aligner` — модуль **Alignment** | `main.py`, Шаг 5 | `ctc_forced_aligner` (git-зависимость), CUDA/CPU auto-detect | путь к аудио, транскрипт, язык | список `{word, start, end}` (word-level timestamps) |
| `io.py` | `SpeakerTimestampReader` | Парсинг RTTM-файла диаризации | `main.py`, Шаг 7.1 | нет внешних | путь к `.rttm` | `List[[start_ms, end_ms, speaker_id:int]]` |
| `io.py` | `TranscriptWriter` | Экспорт диалога в `.txt` и `.srt` — модуль **Export** | `main.py`, Шаг 8 (опционально) | нет внешних | список sentence-speaker словарей | файлы `.temp/output.txt`, `.temp/output.srt` |
| `analysis.py` | `WordSpeakerMapper` | Сопоставление слов со спикерами по временным меткам; повторное выравнивание после пунктуации — модуль **Speaker Mapping** (word-level) | `main.py`, Шаги 7.2, 7.3 | `nltk` (косвенно через `SentenceSpeakerMapper`) | word_timestamps + speaker_timestamps | список `{text, start_time, end_time, speaker}` |
| `analysis.py` | `SentenceSpeakerMapper` | Группировка слов в предложения по спикеру и пунктуации (NLTK `PunktSentenceTokenizer`) — модуль **Speaker Mapping** (sentence-level) | `main.py`, Шаг 7.4 | `nltk.download('punkt')` | word-speaker mapping | список `{speaker, start_time, end_time, text}` = **ssm** (sentence-speaker-mapping) — центральная структура данных всего пайплайна |
| `analysis.py` | `Audio` | Извлечение акустических признаков (модуль **Metrics**): RMS loudness, ZCR, spectral centroid, 4 EQ-полосы, 13 MFCC, min/max frequency, bit depth, каналы | `main.py`, Шаг 15 (создаётся в начале `main()`, но `.properties()` вызывается только на Шаге 15) | `soundfile`, `librosa.feature.mfcc`, `scipy.fft`, `wave` | путь к аудио (**важно: исходный `audio_file_path`, НЕ enhanced/vocal-only версия**) | кортеж из 11 полей + словарь признаков |
| `metrics.py` | `SilenceStats` | Статистика длительностей тишины между репликами (модуль **Metrics**) | `main.py`, Шаг 16 | `numpy` | список сегментов ssm (`start_time`/`end_time`) | пороги (`threshold_std`, `threshold_median_iqr`), суммарная тишина выше порога |
| `utils.py` | `TokenizerUtils` | Поиск токенов с цифрами/символами для подавления в Whisper | `processing.py::Transcriber.transcribe` (условно, при `suppress_numerals=True`) | HuggingFace tokenizer API | tokenizer | список token ID |
| `utils.py` | `Formatter` | `add_indices_to_ssm()` — добавляет индексы к ssm; `format_ssm_as_dialogue()` — форматирует ssm в текстовый диалог для LLM-промптов | `main.py` (Шаг 10), `src/text/llm.py::LLMOrchestrator.generate()` | нет внешних | ssm | ssm с индексами / строка диалога |

### 3.3 `src/text/` — LLM-слой

| Файл | Класс(ы) | Назначение | Кто вызывает | Зависимости | Вход | Выход |
|---|---|---|---|---|---|---|
| `llm.py` | `LLMOrchestrator` | Формирует system/user промпты из `config/prompt.yaml`, вызывает `LanguageModelManager.generate()`, извлекает JSON из ответа регуляркой | `main.py`, Шаги 9–14 | `src.text.model.LanguageModelManager`, `src.audio.utils.Formatter`, `yaml` | имя задачи (`Classification`, `SentimentAnalysis`, ...) + ssm | `dict` с результатом или `{"error": ...}` |
| `llm.py` | `LLMResultHandler` | Валидация классификации ролей (Customer/CSR), fallback на "первый спикер = CSR" при некорректном/отсутствующем результате | `main.py`, Шаг 9.1 | нет внешних | LLM-результат + ssm | ssm с нормализованными метками `speaker` ("Customer"/"CSR") |
| `model.py` | `LanguageModel` (ABC), `LLaMAModel`, `OpenAIModel`, `AzureOpenAIModel` | Абстракция над разными LLM-провайдерами (модуль **LLM**) | `ModelFactory` | `transformers`, `openai`, `torch` | сообщения (messages) | сгенерированный текст |
| `model.py` | `ModelRegistry`, `ModelFactory` | Реестр и фабрика моделей по `model_id` (Registry pattern) | `src/text/__init__.py` (регистрация: `"llama"→LLaMAModel`, `"openai"→OpenAIModel`, `"azure_openai"→AzureOpenAIModel`), `LanguageModelManager.get_model()` | — | `model_id`, config | экземпляр `LanguageModel` |
| `model.py` | `LanguageModelManager` | Кэш моделей с LRU-вытеснением (`OrderedDict`, `cache_size`), асинхронный `generate()` с `asyncio.Lock` | `LLMOrchestrator.__init__` (через `LLMOrchestrator`→нет, напрямую создаётся в `LLMOrchestrator.__init__`) | `torch.cuda` | `model_id`, messages | текст или `None` при ошибке (перехватывается и логируется в `print`) |
| `prompt.py` | `PromptManager` | Отдельный менеджер промптов из YAML с `.format(**kwargs)` | **Никто** — не импортируется нигде в `main.py`/`llm.py`. Дублирует функциональность `LLMOrchestrator._load_prompts()`, но по другому пути (`config/prompts.yaml`, с "s", которого не существует — только `config/prompt.yaml`) | `yaml` | имя промпта | форматированный промпт |
| `utils.py` | `Annotator` | Накопление аннотаций поверх ssm: sentiment, profanity, summary, conflict, topic; финализация в единый `dict` | `main.py`, Шаги 10–14 | нет внешних | ssm + результаты LLM-задач | `{"ssm": [...], "summary": str, "conflict": bool, "topic": str}` |

### 3.4 `src/db/` — персистентность

| Файл | Класс(ы)/содержимое | Назначение | Кто вызывает | Вход | Выход |
|---|---|---|---|---|---|
| `manager.py` | `Database` | Тонкая обёртка над `sqlite3`: `fetch(sql_file)`, `insert(sql_file, params)`, `get_or_insert_topic_id(...)` | `main.py`, Шаги 14, 17.1, 17.2 | путь к `.sql`-файлу + параметры | список кортежей (fetch) / `lastrowid` (insert) |
| `sql/Schema.sql` | DDL | Три таблицы: `Topic` (ID, Name), `File` (метаданные звонка + акустика + summary/conflict/silence), `Utterance` (реплики с speaker/sentiment/profane) | Выполняется вручную (нет миграционного механизма — не вызывается автоматически ни откуда в коде) | — | — |
| `sql/AudioPropertiesInsert.sql` | INSERT в `File` (33 параметра) | | `Database.insert()`, Шаг 17.1 | | |
| `sql/UtteranceInsert.sql` | INSERT в `Utterance` (8 параметров) | | `Database.insert()`, Шаг 17.2, в цикле по каждой реплике | | |
| `sql/TopicFetch.sql` | `SELECT ID, Name FROM Topic` | | `Database.fetch()`, Шаг 14 | | |
| `sql/TopicInsert.sql` | `INSERT INTO Topic (Name) VALUES (?)` | | `Database.get_or_insert_topic_id()` | | |

**Важное наблюдение:** таблица `Utterance` имеет жёсткое ограничение
`Speaker CHECK (Speaker IN ('Customer', 'CSR'))` — схема БД рассчитана исключительно на
бинарную модель "клиент против оператора", хотя диаризация (NeMo, `max_num_speakers: 8`)
технически поддерживает до 8 спикеров. Это несоответствие между возможностями пайплайна и
схемой хранения.

### 3.5 `src/utils/` — сквозные утилиты

| Файл | Класс(ы) | Назначение | Кто вызывает | Вход | Выход |
|---|---|---|---|---|---|
| `utils.py` | `Logger` | Обёртка над `logging` с опциональным `print` | `preprocessing.py::Denoiser` (единственный явный потребитель среди прочитанных файлов) | сообщение | запись в лог/консоль |
| `utils.py` | `Cleaner` | Удаление файлов/директорий (`os.remove`/`shutil.rmtree`) | `main.py`, Шаг 18: `cleaner.cleanup(temp_dir, audio_file_path)` — **удаляет и `.temp`, и исходный входной аудиофайл** | пути | — |
| `utils.py` | `Watcher` | `watchdog.FileSystemEventHandler`: следит за `.data/input`, при появлении `.mp3/.wav/.flac` синхронно вызывает `asyncio.run(callback(path))`; блокирующий `while True: time.sleep(1)` | `main.py`, `if __name__ == "__main__"` | директория, callback | — (бесконечный блокирующий цикл) |

### 3.6 `config/`

| Файл | Назначение |
|---|---|
| `config.yaml` | `runtime` (device/compute_type/cuda_alloc_conf), `language`, `models.{llama,openai,azure_openai,mpsenet}` — секреты подставляются через `${ENV_VAR}` и `os.getenv` в `LanguageModelManager._load_full_config()` |
| `prompt.yaml` | 6 промптов: `Classification`, `SentimentAnalysis`, `ProfanityWordDetection`, `Summary`, `ConflictDetection`, `TopicDetection` — все жёстко заточены под сценарий "звонок в контакт-центр между Customer и CSR" |
| `nemo/diar_infer_telephonic.yaml` | Полный конфиг NeMo `ClusterDiarizer`: VAD (`vad_multilingual_marblenet`), speaker embeddings (`titanet_large`, мультимасштабные окна), clustering (до 8 спикеров), MSDD-модель (`diar_msdd_telephonic`), ASR-модуль (`stt_en_conformer_ctc_large`, не используется в основном пайплайне — Whisper используется отдельно и независимо) |

### 3.7 `automation/`

| Файл | Назначение |
|---|---|
| `service/callytics.service` | systemd unit; **жёстко зашитые абсолютные пути** (`/home/bunyamin/Callytics`, conda env `Callytics`); `Restart=on-failure`; предполагает, что весь процесс (модели + watcher) держится в памяти постоянно на одной машине |

### 3.8 `.data/`, `.db/`, `.docs/`

- `.data/example/` — тестовые аудио на 4 языках + один "шумный" пример для ручного прогона `Denoiser`/`SpeechEnhancement` через их `if __name__` блоки.
- `.data/groundtruth/speakerverification/` — датасет для верификации диктора (звонки + SRT + voiceprint-сэмплы + `DatasetCard.md` + `LICENSE`) — это **эталонные данные для валидации/тестирования качества**, но нет ни одного скрипта, который бы их фактически использовал для автоматической проверки точности (что согласуется с отсутствием тестов).
- `.db/Callytics.sqlite` — бинарный файл БД (схема соответствует `Schema.sql`).
- `.docs/` — presentation (PDF), изображения архитектуры (`Callytics.drawio/.png/.svg/.gif`), `CONTRIBUTING.md`, `RESOURCES.md` — вспомогательная документация, не код.

## 4. Обнаруженные архитектурные проблемы (только наблюдения, без исправлений)

1. **`AzureOpenAIModel` (`src/text/model.py`) почти наверняка не рабочий с текущей закреплённой
   версией `openai==1.57.0`.** Класс использует устаревший pre-1.0 интерфейс
   (`openai.api_type = "azure"`, `openai.ChatCompletion.create(...)`), которого больше нет в
   openai SDK ≥ 1.0 (используется класс `OpenAI`, как в соседнем `OpenAIModel`). При вызове
   `AzureOpenAIModel.generate()` в текущем окружении ожидается `AttributeError`.
2. **`Denoiser` (`src/audio/preprocessing.py`) — мёртвый код.** Не импортируется нигде в
   `main.py`; функционально перекрыт `SpeechEnhancement` (MPSENet). Есть только в собственном
   `if __name__ == "__main__"` демо-блоке.
3. **`PromptManager` (`src/text/prompt.py`) — мёртвый код**, дублирующий загрузку промптов,
   которую фактически делает `LLMOrchestrator._load_prompts()`. Ссылается на несуществующий
   `config/prompts.yaml` (с "s") вместо реального `config/prompt.yaml`.
4. **Удаление исходного аудио — заложено в пайплайн дважды:**
   `DialogueDetecting(delete_original=True)` (Шаг 1, если диалог не найден) и
   `Cleaner.cleanup(temp_dir, audio_file_path)` (Шаг 18, после успешной обработки). Оригинальная
   запись звонка нигде не сохраняется на диске после завершения пайплайна.
5. **Акустические метрики (Шаг 15, класс `Audio`) считаются по исходному файлу**, а не по
   версии после `SpeechEnhancement`/Demucs — то есть шум и фон физически участвуют в
   RMS/EQ/MFCC-признаках, а не только "чистый" голос.
6. **Отсутствие очереди задач.** `Watcher.on_created` вызывает `asyncio.run(callback(...))`
   синхронно в потоке `watchdog`; при появлении нескольких файлов подряд обработка строго
   последовательна, нет журнала ошибок/ретраев/dead-letter.
7. **Схема БД жёстко бинарна** (`Speaker IN ('Customer','CSR')`), хотя диаризация допускает до
   8 спикеров.

Детальный разбор по каждому модулю — см. `MODULES.md`. Выводы о том, что переиспользовать,
заменить или удалить для будущей QA-платформы — см. `REUSE.md`. Диаграмма полного пайплайна —
см. `PIPELINE.md`.
