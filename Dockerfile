# syntax=docker/dockerfile:1

# Matches the Python version the test suite runs on.
ARG PYTHON_VERSION=3.14

# --- Stage 1: install dependencies and NLTK data -----------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake NLTK data into the image so containers never download it at startup
# (and can run without outbound internet access). The downloader writes its
# zips as root-only (0600), so open them up for the non-root runtime user.
RUN python -m nltk.downloader -q -d /opt/nltk_data \
        punkt_tab stopwords wordnet vader_lexicon \
    && chmod -R a+rX /opt/nltk_data

# --- Stage 2: slim runtime image ---------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    NLTK_DATA=/opt/nltk_data \
    UPLOAD_DIR=/tmp/uploads \
    PREFECT_HOME=/tmp/prefect \
    PREFECT_SERVER_ANALYTICS_ENABLED=false

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/nltk_data /opt/nltk_data
COPY app/ app/
COPY main.py .

USER 10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

# One worker per container: flow runs execute in an in-process thread pool, so
# scale by adding replicas rather than uvicorn workers.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
