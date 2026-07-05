# NikelPower

Веб-приложение для загрузки научно-технических документов (PDF, DOCX, PPTX), извлечения сущностей, построения графа знаний и RAG-поиска через Yandex Cloud AI.

**Стек:** Streamlit · Neo4j · PostgreSQL · Redis/RQ · Yandex GPT / Embeddings / Vision

---

## Содержание

1. [Требования](#требования)
2. [Быстрый старт](#быстрый-старт)
3. [Подробная установка](#подробная-установка)
4. [Настройка `.env`](#настройка-env)
5. [Запуск сервисов](#запуск-сервисов)
6. [Проверка работы](#проверка-работы)
7. [Структура проекта](#структура-проекта)
8. [Обновление и пересборка](#обновление-и-пересборка)
9. [Резервное копирование](#резервное-копирование)
10. [Устранение неполадок](#устранение-неполадок)

---

## Требования

| Компонент | Минимум |
|-----------|---------|
| **ОС** | Windows 10/11, Linux или macOS |
| **Docker Desktop** | 4.x+ (с Docker Compose v2) |
| **RAM** | 8 ГБ (рекомендуется 16 ГБ — Neo4j использует до 4 ГБ) |
| **Диск** | 10+ ГБ свободного места |
| **Yandex Cloud** | Каталог с включённым AI Studio, API-ключ, модели LLM и embeddings |

Порты на хосте должны быть свободны:

| Порт | Сервис |
|------|--------|
| 8501 | Streamlit UI |
| 7474 | Neo4j Browser |
| 7687 | Neo4j Bolt |
| 5432 | PostgreSQL |
| 6379 | Redis (только при профиле `worker`) |

---

## Быстрый старт

```powershell
# 1. Клонировать репозиторий
git clone <URL-репозитория> nikelpower_2
cd nikelpower_2

# 2. Создать конфигурацию
copy .env.example .env
# Отредактировать .env — заполнить ключи Yandex Cloud (см. ниже)

# 3. Создать каталоги для данных
mkdir data\documents, data\ingestion -Force

# 4. Запустить UI + базы данных
docker compose -p nikelpower up -d

# 5. Запустить фоновый worker (загрузка документов)
docker compose -p nikelpower --profile worker up -d
```

Откройте в браузере: **http://localhost:8501**

---

## Подробная установка

### 1. Установить Docker

- **Windows / macOS:** [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- **Linux:** Docker Engine + Docker Compose plugin

Проверка:

```powershell
docker --version
docker compose version
```

### 2. Получить доступ к Yandex Cloud AI

1. Создайте [каталог](https://cloud.yandex.ru/docs/resource-manager/operations/folder/create) в Yandex Cloud.
2. Включите [Yandex AI Studio](https://cloud.yandex.ru/docs/ai-studio/).
3. Создайте [API-ключ сервисного аккаунта](https://cloud.yandex.ru/docs/iam/operations/api-key/create).
4. Запишите:
   - **ID каталога** (`YANDEX_CLOUD_FOLDER`)
   - **API-ключ** (`YANDEX_CLOUD_API_KEY`)
5. Подключите модели в AI Studio (или используйте URI напрямую):
   - LLM для чата и извлечения сущностей, например:  
     `gpt://<folder_id>/yandexgpt/latest`
   - Embeddings, например:  
     `emb://<folder_id>/text-search-doc/latest`
   - Vision (опционально, для описания изображений в документах):  
     `gpt://<folder_id>/<model>/latest`

### 3. Настроить переменные окружения

```powershell
copy .env.example .env
```

Откройте `.env` в текстовом редакторе и заполните обязательные поля (подробнее в [разделе ниже](#настройка-env)).

> **Важно:** файл `.env` не коммитится в git. На новом компьютере его нужно создать заново.

### 4. Подготовить каталоги данных

```powershell
mkdir data\documents\uploads -Force
mkdir data\ingestion -Force
```

Эти каталоги монтируются в контейнеры — загруженные документы и состояние ingestion сохраняются на диске хоста.

### 5. Собрать и запустить контейнеры

Первый запуск (сборка образов может занять 10–20 минут):

```powershell
docker compose -p nikelpower build
docker compose -p nikelpower up -d
docker compose -p nikelpower --profile worker up -d
```

---

## Настройка `.env`

### Обязательные параметры Yandex Cloud

```env
YANDEX_CLOUD_FOLDER=b1gxxxxxxxxxx
YANDEX_CLOUD_API_KEY=AQVNxxxxxxxx
YANDEX_CLOUD_MODEL=gpt://b1gxxxxxxxxxx/yandexgpt/latest
YANDEX_EMBEDDING_MODEL=emb://b1gxxxxxxxxxx/text-search-doc/latest
```

### Рекомендуемые параметры

```env
# Лимит токенов на одну пользовательскую операцию (загрузка / чат)
TOKEN_LIMIT=1000000

# Порог релевантности RAG-поиска (0.0–1.0)
EMBEDDING_SIMILARITY_THRESHOLD=0.82

# Размерность эмбеддингов (должна совпадать с моделью Yandex)
EMBEDDING_DIMENSIONS=256
```

### Пароли баз данных (смените в production)

```env
NEO4J_PASSWORD=nikelpower2026
POSTGRES_PASSWORD=nikelpower2026
```

### Параметры ingestion (при необходимости)

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `CHUNK_MAX_TOKENS` | 800 | Максимальный размер чанка для RAG |
| `EMBEDDING_MAX_INPUT_TOKENS` | 1800 | Лимит токенов на один запрос embedding |
| `MAX_VLM_IMAGES` | 40 | Сколько изображений анализировать VLM на документ |
| `ANALYZE_DOCUMENT_IMAGES` | true | Включить описание рисунков |
| `ENABLE_GRAPHITI_ENRICHMENT` | true | Обогащение графа через Graphiti |
| `FORCE_REINGEST` | false | Перезагружать уже обработанные документы |

Полный список — в файле [`.env.example`](.env.example).

---

## Запуск сервисов

Имя проекта Docker Compose: `nikelpower` (флаг `-p nikelpower`).

### Только UI и базы (без загрузки документов в фоне)

```powershell
docker compose -p nikelpower up -d
```

Запускаются: **backend** (Streamlit), **neo4j**, **postgres**.

### Полный режим (с фоновой обработкой документов)

```powershell
docker compose -p nikelpower --profile worker up -d
```

Дополнительно: **redis**, **worker**.

### Остановка

```powershell
docker compose -p nikelpower --profile worker down
```

### Просмотр логов

```powershell
docker compose -p nikelpower logs -f backend
docker compose -p nikelpower logs -f worker
```

### Статус контейнеров

```powershell
docker compose -p nikelpower ps
```

---

## Проверка работы

| Проверка | URL / команда |
|----------|---------------|
| Веб-интерфейс | http://localhost:8501 |
| Neo4j Browser | http://localhost:7474 (логин: `neo4j`, пароль из `.env`) |
| Backend жив | `docker compose -p nikelpower ps` — статус `healthy` / `running` |
| Worker обрабатывает задачи | `docker compose -p nikelpower logs worker` |

### Первый сценарий

1. Откройте **«Загрузка документов»** в боковом меню.
2. Загрузите PDF, DOCX или PPTX, выберите категорию, нажмите **«Загрузить в базу данных»**.
3. Дождитесь завершения (нужен запущенный **worker**).
4. Перейдите в **«Чат с LLM»** и задайте вопрос по содержимому документа.

---

## Структура проекта

```
nikelpower_2/
├── .env.example          # Шаблон конфигурации
├── .env                  # Локальная конфигурация (не в git)
├── docker-compose.yml    # Оркестрация сервисов
├── data/
│   ├── documents/        # Загруженные файлы и архивы
│   └── ingestion/        # Состояние пайплайна, jobs, prepared-тексты
└── backend/
    ├── Dockerfile        # Образ Streamlit UI
    ├── Dockerfile.worker # Образ фонового worker
    ├── requirements.txt
    └── app/
        ├── main.py       # Точка входа Streamlit
        ├── config.py     # Настройки из .env
        ├── ingestion/    # Пайплайн загрузки документов
        ├── services/     # RAG, чат, граф
        └── ui/           # Вкладки интерфейса
```

---

## Обновление и пересборка

После изменения кода или `.env`:

```powershell
# Пересобрать образы
docker compose -p nikelpower build backend
docker compose -p nikelpower --profile worker build worker

# Перезапустить
docker compose -p nikelpower up -d
docker compose -p nikelpower --profile worker up -d
```

> После изменения `.env` перезапустите **и backend, и worker** — оба читают одни и те же переменные (в т.ч. `TOKEN_LIMIT`).

---

## Резервное копирование

Для переноса на другой компьютер сохраните:

| Что | Где |
|-----|-----|
| Конфигурация | `.env` |
| Загруженные документы | `data/documents/` |
| Состояние ingestion | `data/ingestion/` |
| Neo4j | Docker volume `nikelpower_neo4j_data` |
| PostgreSQL | Docker volume `nikelpower_postgres_data` |

Экспорт Docker volumes:

```powershell
docker run --rm -v nikelpower_neo4j_data:/data -v ${PWD}:/backup alpine tar czf /backup/neo4j_backup.tar.gz -C /data .
docker run --rm -v nikelpower_postgres_data:/data -v ${PWD}:/backup alpine tar czf /backup/postgres_backup.tar.gz -C /data .
```

На новом компьютере — развернуть проект, восстановить volumes и каталог `data/`.

---

## Устранение неполадок

### Порт уже занят

Измените проброс порта в `docker-compose.yml`, например `"8502:8501"` для UI.

### «Задача не найдена» / загрузка зависла

Убедитесь, что worker запущен:

```powershell
docker compose -p nikelpower --profile worker up -d worker
docker compose -p nikelpower logs worker
```

### Ошибка embedding / LLM 400 / 401

- Проверьте `YANDEX_CLOUD_API_KEY` и `YANDEX_CLOUD_FOLDER`.
- Убедитесь, что URI моделей содержат правильный ID каталога.
- Перезапустите backend и worker после правки `.env`.

### TOKEN_LIMIT / документ не загружается

Лимит токенов задаётся в `.env` (`TOKEN_LIMIT`). После изменения перезапустите **оба** контейнера: `backend` и `worker`.

### Neo4j не стартует (мало памяти)

Уменьшите в `.env`:

```env
NEO4J_HEAP=1G
NEO4J_PAGECACHE=1G
```

### Поиск в чате ничего не находит

- Убедитесь, что документ успешно загружен (в Neo4j есть `DocumentChunk`).
- Проверьте фильтры «Отечественные / Зарубежные источники» в чате.
- При необходимости снизьте `EMBEDDING_SIMILARITY_THRESHOLD` до `0.65–0.70`.

### Полная переустановка (удалить все данные)

```powershell
docker compose -p nikelpower --profile worker down -v
Remove-Item -Recurse -Force data\documents\*, data\ingestion\*
docker compose -p nikelpower build
docker compose -p nikelpower --profile worker up -d
```

---

## Локальная разработка без Docker (опционально)

Требуется Python 3.11+, установленный LibreOffice, локальные Neo4j, PostgreSQL и Redis.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
pip install -r backend\requirements-worker.txt

copy .env.example .env
# В .env указать NEO4J_URI=bolt://localhost:7687 и localhost для Postgres/Redis

cd backend
streamlit run app/main.py
```

Worker в отдельном терминале:

```powershell
cd backend
python -m app.ingestion.worker
```

---

## Лицензия и поддержка

Внутренний проект NikelPower. По вопросам развёртывания обращайтесь к команде разработки.
