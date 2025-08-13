# ---- Base image ----
FROM python:3.11-slim

# Prevent prompts
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies (tesseract + chrome + fonts)
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates unzip curl \
    tesseract-ocr fonts-dejavu libtesseract-dev \
    libglib2.0-0 libnss3 libxi6 libxcursor1 libxdamage1 libxrandr2 libxss1 libxtst6 \
    libatk1.0-0 libatk-bridge2.0-0 libxcomposite1 libxkbcommon0 libasound2 libdrm2 libgbm1 \
    libpango-1.0-0 libpangocairo-1.0-0 libx11-xcb1 \
    && rm -rf /var/lib/apt/lists/* \
    && echo "Adding Google Chrome repo" \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
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
    OPENAI_API_KEY="" \
    DISABLE_SELENIUM="true" \
    CHROME_BIN="/usr/bin/google-chrome" \
    CHROME_PATH="/usr/bin/google-chrome"

# Launch
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
