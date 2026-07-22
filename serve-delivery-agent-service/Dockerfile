FROM python:3.11-slim

WORKDIR /app

# curl is needed by this image's own HEALTHCHECK (docker-compose.yml) —
# python:3.11-slim doesn't include it by default.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8010

CMD ["python", "main.py"]
