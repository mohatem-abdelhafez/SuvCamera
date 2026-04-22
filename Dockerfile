FROM python:3.11-slim

# System dependencies for OpenCV headless
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps — swap opencv-python for headless (no display needed)
COPY requirements.txt .
RUN sed 's/^opencv-python/opencv-python-headless/' requirements.txt \
    | pip install --no-cache-dir -r /dev/stdin

COPY . .

RUN mkdir -p data/uploads

EXPOSE 8000

CMD ["python", "main.py"]
