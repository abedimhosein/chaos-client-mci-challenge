FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system --gid 1000 appuser \
    && adduser --system --uid 1000 --gid 1000 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

COPY app ./app
COPY main.py .

USER 1000:1000

CMD ["python", "main.py"]