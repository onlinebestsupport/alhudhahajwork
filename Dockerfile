# Alhudha Haj Travel System — Railway OCR-capable runtime
# Install system executables explicitly because pytesseract alone is only a Python wrapper.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && pip install --prefer-binary -r /app/requirements.txt

COPY . /app

# Fail during the image build, with the exact source file and line, rather
# than allowing Railway to restart a container that cannot import the app.
RUN python -m compileall -q core main.py

CMD ["python", "main.py"]
