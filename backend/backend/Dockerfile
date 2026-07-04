# Облегчённый образ: Streamlit UI + LibreOffice + парсинг PDF/DOCX/PPTX
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=600
ENV PIP_RETRIES=10

# LibreOffice headless: DOCX/PPTX → PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    libreoffice-impress \
    libreoffice-core \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    success=0 && \
    for i in 1 2 3 4 5; do \
      echo "=== pip attempt $i/5 ===" && \
      pip install --retries 10 -r requirements.txt && success=1 && break; \
      echo "pip attempt $i failed, retry in 30s..."; sleep 30; \
    done && \
    test "$success" -eq 1

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0"]
