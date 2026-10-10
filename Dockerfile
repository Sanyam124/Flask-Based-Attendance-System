FROM python:3.10-slim

# Install system dependencies for OpenCV and image operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install pre-compiled dlib binary wheel to prevent out-of-memory build on cloud hosts
RUN pip install --no-cache-dir dlib-bin

# Install remaining dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose port (Render/Railway dynamically injects $PORT)
EXPOSE 5000

ENV PYTHONUNBUFFERED=1

CMD ["python", "app.py"]
