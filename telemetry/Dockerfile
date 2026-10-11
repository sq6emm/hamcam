FROM python:3.12-slim
RUN pip install --no-cache-dir aiohttp==3.10.10
WORKDIR /app
COPY telemetry.py .
USER 1000:1000
CMD ["python", "-u", "telemetry.py"]
