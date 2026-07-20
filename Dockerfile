# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    APP_ENV=production

WORKDIR /app

RUN groupadd --system lessonpack \
    && useradd --system --gid lessonpack --home-dir /app lessonpack

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY --chown=lessonpack:lessonpack src ./src
COPY --chown=lessonpack:lessonpack config.example.yaml ./config.example.yaml
COPY --chown=lessonpack:lessonpack config.yaml ./config.yaml

USER lessonpack

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]

CMD ["uvicorn", "lectureops_agent.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
