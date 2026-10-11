FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# main.py, engine, data/ (prices, gurus, caches) and private_twins/ (mounted at /private)
COPY . .

# One worker only: run state for both backends is held in process memory.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
