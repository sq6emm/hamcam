# hamcam telemetry: rotator, weather, beacons, TLEs, summits; build context = repository root
FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/sq6emm/hamcam" \
      org.opencontainers.image.description="hamcam telemetry service (rotctld, weather, IARU beacons, CelesTrak TLEs, SOTA summits)" \
      org.opencontainers.image.licenses="PolyForm-Noncommercial-1.0.0"
RUN pip install --no-cache-dir aiohttp==3.10.10 && mkdir -p /data && chown 1000:1000 /data
WORKDIR /app
COPY telemetry/telemetry.py .
# example configuration; mount your own directory over /config
COPY deploy/objects.json /config/objects.json
USER 1000:1000
VOLUME /data
CMD ["python", "-u", "telemetry.py"]
