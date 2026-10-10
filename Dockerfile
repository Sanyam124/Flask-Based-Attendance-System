FROM python:3.10-slim

# Install system libraries for OpenCV and runtime image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. Install pre-compiled dlib Linux binary wheel (no C++ build needed, uses ~50MB RAM)
RUN pip install --no-cache-dir dlib-bin

# 2. Install face-recognition without triggering source compilation
RUN pip install --no-cache-dir --no-deps face-recognition

# 3. Install remaining application dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application files
COPY . .

# Expose port (Render automatically injects $PORT)
EXPOSE 5000

ENV PYTHONUNBUFFERED=1

CMD ["python", "app.py"]
