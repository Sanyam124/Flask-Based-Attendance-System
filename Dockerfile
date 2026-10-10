FROM python:3.10-slim

# Install system dependencies for dlib, OpenCV, and compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose port (default 5000, Render/Railway injects $PORT)
EXPOSE 5000

ENV PYTHONUNBUFFERED=1

CMD ["python", "app.py"]
