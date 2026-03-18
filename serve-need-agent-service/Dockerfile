FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/

COPY . .

EXPOSE 8005

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8005"]
