# ---- Base image ----
FROM python:3.11-slim

# Prevent prompts
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies (tesseract + chromium + fonts)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    wget gnupg unzip \
    chromium chromium-driver \
    libglib2.0-0 libnss3 libgconf-2-4 libxi6 libxcursor1 libxdamage1 libxrandr2 libxss1 libxtst6 \
    libatk1.0-0 libatk-bridge2.0-0 libxcomposite1 libxkbcommon0 libasound2 libdrm2 libwayland-server0 \
    libxshmfence1 libgbm1 libpango-1.0-0 libpangocairo-1.0-0 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Create app dir
WORKDIR /app

# Copy dependency manifest first (layer caching)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Expose Streamlit default port
EXPOSE 8501

# Streamlit config to allow container usage
ENV STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    OPENAI_API_KEY=""

# Launch
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
