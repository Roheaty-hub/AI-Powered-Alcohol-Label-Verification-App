FROM python:3.12-slim

# Tesseract runs inside the container: no calls to external OCR/ML endpoints.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_THREAD_LIMIT=1 \
    PORT=8000

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY samples ./samples
COPY wsgi.py .

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
# One worker process: batch jobs live in that process's memory, so polling must
# hit the same process. Concurrency comes from threads + the batch thread pool.
CMD gunicorn --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:${PORT} wsgi:app
