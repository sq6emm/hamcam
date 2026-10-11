FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir opencv-python-headless==4.10.0.84 numpy==2.1.2
WORKDIR /app
COPY fov_measure.py .
CMD ["python", "-u", "fov_measure.py"]
