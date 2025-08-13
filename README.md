# AI Quiz Helper

Streamlit app for:
- OCR of screenshot images (pytesseract)
- Scraping Google Forms questions (fast static parse + Selenium fallback)
- Getting suggested answers via OpenAI or OpenRouter models

## Run Locally

```bash
# (Windows PowerShell) create and activate venv
python -m venv .venv
. .venv/Scripts/Activate
pip install -r requirements.txt
streamlit run app.py
```

## Environment Variables

Set one of:
- `OPENAI_API_KEY` for OpenAI
- `OPENAI_API_KEY` with an OpenRouter key (select provider OpenRouter in sidebar)

Optional (OpenRouter):
- `APP_PUBLIC_URL` (used for Referer header)

PowerShell examples:
```powershell
$env:OPENAI_API_KEY = "sk-your-key"
$env:APP_PUBLIC_URL = "https://yourapp.example.com"
```

## Deployment Options

### 1. Streamlit Community Cloud (no Selenium)
- Push repo to GitHub.
- In `app.py`, Selenium may not work due to sandbox/browser limits. The fast (non-Selenium) parser will still try.
- Add secrets in the Streamlit Cloud UI (Secrets panel) with `OPENAI_API_KEY`.

### 2. Docker (recommended for Selenium)
Create `Dockerfile` (example soon) and deploy to any container host (Railway, Render, Fly.io, AWS, Azure, GCP).

### 3. Render.com (simple)
- New Web Service -> build command `pip install -r requirements.txt`
- Start command `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`
- Add env var `OPENAI_API_KEY`.

### 4. Railway.app / Fly.io
Use Dockerfile for consistent Chrome + Tesseract installation.

## TODO
- Add dynamic model listing from OpenRouter
- Add local model fallback (transformers)

## License
MIT
