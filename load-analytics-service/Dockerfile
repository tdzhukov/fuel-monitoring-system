FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY load_analytics_service.py .

ENV METRICS_PORT=8000
ENV REFRESH_INTERVAL_SECONDS=60

EXPOSE 8000

CMD ["python", "load_analytics_service.py"]
