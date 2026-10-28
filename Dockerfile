FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements-render.txt .
RUN pip install --no-cache-dir -r requirements-render.txt

# Copy application files
COPY . .

# Render default port
ENV PORT=10000
EXPOSE 10000

CMD ["python", "render_server.py"]
