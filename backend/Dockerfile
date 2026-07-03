# Облегчённый образ: только Streamlit UI (~2–4 мин сборки)
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=300
ENV PIP_RETRIES=5

COPY requirements.txt .
RUN pip install --no-cache-dir --retries 5 -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0"]
