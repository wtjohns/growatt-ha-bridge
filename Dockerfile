FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY growatt_poller.py .

# Run as non-root user
RUN adduser --disabled-password --gecos "" appuser
USER appuser

CMD ["python", "-u", "growatt_poller.py"]
