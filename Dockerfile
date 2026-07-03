FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY config/ config/
COPY templates/ templates/
COPY src/ src/
COPY data/generated/ data/generated/

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home appuser \
    && mkdir -p data/reports data/structure_cache \
    && chown -R appuser:appuser /app
USER appuser

CMD ["python", "-m", "src.main"]
