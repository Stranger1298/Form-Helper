import streamlit as st
from PIL import Image
import pytesseract
import openai
import os
import time
import traceback
import re
import json
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from bs4 import BeautifulSoup

# --- OpenAI API Key Handling (sidebar + env + optional secrets) ---
if 'user_api_key' not in st.session_state:
    st.session_state['user_api_key'] = ''

api_key_input = st.sidebar.text_input("OpenAI API Key", type="password", help="Not saved to disk; session memory only.")
if api_key_input:
    st.session_state['user_api_key'] = api_key_input.strip()

def _resolve_api_key():
    if st.session_state.get('user_api_key'):
        return st.session_state['user_api_key']
    env_key = os.getenv("OPENAI_API_KEY")
    if env_key:
        return env_key
    try:
        if 'OPENAI_API_KEY' in st.secrets:
            return st.secrets['OPENAI_API_KEY']
    except Exception:
        pass
    return None

resolved_api_key = _resolve_api_key()
if resolved_api_key:
    openai.api_key = resolved_api_key

# --- Streamlit UI setup ---
st.set_page_config(page_title="AI Quiz Helper", layout="centered")
st.title("📝 AI Quiz Helper — Ethical Assistant")

mode = st.sidebar.radio("Choose mode", ["Screenshot/Text", "Google Form Link"])

# Provider selection (OpenAI vs OpenRouter)
provider = st.sidebar.selectbox("Provider", ["OpenAI", "OpenRouter"], index=0, help="Choose API provider.")

# Dynamic model choices per provider
OPENAI_MODELS = ["gpt-4o", "gpt-4o-mini", "gpt-4", "gpt-3.5-turbo"]
OPENROUTER_MODELS = [
    "openai/gpt-4o-mini",
    "openai/gpt-4o",
    "meta-llama/llama-3.1-8b-instruct:free",
    "google/gemini-flash-1.5",
]
model_choices = OPENAI_MODELS if provider == "OpenAI" else OPENROUTER_MODELS
model = st.sidebar.selectbox("Model", model_choices, index=0)
temp = st.sidebar.slider("Temperature", 0.0, 1.0, 0.0, 0.01)

# --- Helper Functions ---

@st.cache_resource(show_spinner=False)
def _get_openai_client(api_key: str | None, provider: str, referer: str | None = None):
    """Instantiate OpenAI-compatible client with provider-specific base_url and headers.
    Cached per (api_key, provider).
    """
    from openai import OpenAI  # type: ignore
    base_url = None
    extra_headers = {}
    if provider == "OpenRouter":
        base_url = "https://openrouter.ai/api/v1"
        # OpenRouter encourages Referer + X-Title headers.
        if referer:
            extra_headers["HTTP-Referer"] = referer
        extra_headers["X-Title"] = "AI Quiz Helper"
    kwargs = {}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    if extra_headers:
        kwargs["default_headers"] = extra_headers
    return OpenAI(**kwargs)

def query_openai_chat(prompt, model="gpt-4o", temp=0.0):
    key = _resolve_api_key()
    if not key:
        return "ERROR: API key missing. Enter it in the sidebar or set OPENAI_API_KEY."
    try:
        # Basic heuristic: OpenRouter keys often start with 'sk-or-' but user may choose provider manually.
        client = _get_openai_client(key, provider, referer=os.getenv("APP_PUBLIC_URL", "http://localhost:8501"))
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temp,
        )
        if not resp.choices:
            return "No completion returned."
        msg = resp.choices[0].message
        content = getattr(msg, 'content', '') or ''
        return content.strip()
    except Exception as e:
        err = str(e)
        if 'rate_limit' in err or '429' in err:
            return 'Rate limit hit. Wait and retry or lower usage.'
        if 'insufficient_quota' in err:
            return 'Quota exceeded. Check billing/plan or use another provider.'
        if 'Incorrect API key' in err or '401' in err:
            return 'Invalid API key for selected provider.'
        if 'model' in err and 'not found' in err:
            return 'Model not available for this key/provider.'
        return f'API error: {err}'

def build_prompt(question, choices=None):
    base = "You are an assistant that answers quiz questions.\n"
    if choices:
        choice_lines = "\n".join(f"- {c}" for c in choices)
        task = f"""Question:
{question}

Choices:
{choice_lines}

Return:
ANSWER: <choice>
EXPLANATION: <short reason>
"""
    else:
        task = f"""Question:
{question}

Return:
ANSWER: <short answer>
EXPLANATION: <short reason>
"""
    return base + task

@st.cache_resource(show_spinner=False)
def start_selenium_driver():
    """Create (and cache) a headless Chrome driver with perf optimizations."""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920x1080")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--remote-debugging-port=9222")
    # Reduce resource usage:
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--disable-default-apps")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-sync")
    chrome_options.add_argument("--metrics-recording-only")
    chrome_prefs = {"profile.managed_default_content_settings.images": 2}
    chrome_options.experimental_options["prefs"] = chrome_prefs
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

@st.cache_data(show_spinner=False, ttl=600)
def fast_scrape_google_form(url: str):
    """Fast path: parse the embedded FB_PUBLIC_LOAD_DATA_ structure without Selenium.
    Returns list of {question, choices or None}. If structure not found, returns None.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        # Find the JS variable
        m = re.search(r"var FB_PUBLIC_LOAD_DATA_ = (.*?);\\s*</script>", r.text, re.DOTALL)
        if not m:
            return None
        raw = m.group(1)
        # The content is a JSON-like array. Load with json.
        data = json.loads(raw)
        # Empirical structure: questions often under data[1][1]
        container = None
        try:
            container = data[1][1]
        except Exception:
            return None
        results = []
        for q in container:
            # Each q is an array; based on common structure: [id, questionText, helpText, ... , optionsStruct]
            if not isinstance(q, list) or len(q) < 2:
                continue
            qtext = (q[1] or "").strip()
            if not qtext:
                continue
            choices = None
            # Options often reside in q[4][0][1] or q[4][0][0]
            try:
                opt_root = q[4]
                if isinstance(opt_root, list):
                    # Flatten plausible option candidates
                    cand_opts = []
                    for branch in opt_root:
                        if isinstance(branch, list):
                            for node in branch:
                                if isinstance(node, list):
                                    # Typical node: [optionText, ...]
                                    if node and isinstance(node[0], str):
                                        cand_opts.append(node[0].strip())
                    cand_opts = [c for c in cand_opts if c]
                    if cand_opts:
                        # Remove duplicates preserving order
                        seen = set()
                        dedup = []
                        for c in cand_opts:
                            if c not in seen:
                                dedup.append(c)
                                seen.add(c)
                        choices = dedup[:20]
            except Exception:
                pass
            results.append({"question": qtext, "choices": choices})
        return results if results else None
    except Exception:
        return None

def selenium_scrape_google_form(url, timeout=15):
    """Selenium fallback scraping (slower)."""
    results = []
    driver = start_selenium_driver()
    try:
        driver.set_page_load_timeout(timeout)
        driver.get(url)
        # Use dynamic wait instead of fixed sleep where practical
        time.sleep(1.2)
        items = driver.find_elements(By.CSS_SELECTOR, 'div[role="listitem"]')
        if not items:
            items = driver.find_elements(By.CSS_SELECTOR, 'div[class*="freebirdFormviewerComponentsQuestion"]')
        for item in items:
            try:
                qtext = ""
                try:
                    qtitle = item.find_element(By.CSS_SELECTOR, 'div[class*="Title"], div[class*="title"], .freebirdFormviewerComponentsQuestionBaseTitle')
                    qtext = qtitle.text.strip()
                except NoSuchElementException:
                    txt = item.text.strip()
                    qtext = txt.split('\n')[0] if txt else ""
                choices = []
                option_selectors = [
                    'div[role="radio"]',
                    'div[role="checkbox"]',
                    'div[class*="exportOption"]',
                    'div[class*="Choice"]',
                    'div.freebirdFormviewerComponentsQuestionRadioChoice',
                    'div.freebirdFormviewerComponentsQuestionCheckboxChoice'
                ]
                opts = []
                for sel in option_selectors:
                    found = item.find_elements(By.CSS_SELECTOR, sel)
                    if found:
                        opts = found
                        break
                if opts:
                    for o in opts:
                        text = o.text.strip()
                        if text:
                            choices.append(text.split('\n')[0].strip())
                else:
                    child_text = item.text.strip().split('\n')
                    if child_text and qtext and child_text[0].strip() == qtext.strip():
                        child_text = child_text[1:]
                    cand = [c.strip() for c in child_text if 1 < len(c.strip()) < 120]
                    if len(cand) >= 2:
                        choices = cand[:15]
                qtext = qtext.replace('Required', '').strip()
                if qtext:
                    results.append({"question": qtext, "choices": choices if choices else None})
            except Exception:
                continue
    except WebDriverException as e:
        st.error(f"Selenium error while scraping: {e}")
    return results

def scrape_google_form(url, timeout=15):
    """Unified scraping: try fast JSON parse first, fallback to Selenium if needed."""
    t0 = time.time()
    fast = fast_scrape_google_form(url)
    method = "fast"
    if not fast:
        method = "selenium"
        fast = selenium_scrape_google_form(url, timeout=timeout)
    elapsed = (time.time() - t0) * 1000
    # Attach perf metadata (not shown to user unless debug enabled)
    st.session_state["last_scrape_perf"] = {"method": method, "ms": round(elapsed, 1)}
    return fast or []


# --- Mode 1: Screenshot/Text ---
if mode == "Screenshot/Text":
    uploaded_file = st.file_uploader("Upload screenshot (optional)", type=["png","jpg","jpeg"])
    paste_text = st.text_area("Or paste question text here (editable)")

    extracted_text = ""
    if uploaded_file:
        image = Image.open(uploaded_file).convert("RGB")
        st.image(image, caption="Uploaded image", use_column_width=True)
        with st.spinner("Running OCR..."):
            extracted_text = pytesseract.image_to_string(image).strip()
        st.success("OCR finished. Edit text below if needed.")

    question_text = paste_text if paste_text else extracted_text
    question_text = st.text_area("Question (edit if needed)", value=question_text, height=150)

    choices_input = st.text_input("Comma-separated choices (optional)")
    choices = [c.strip() for c in choices_input.split(",") if c.strip()] if choices_input else None

    if st.button("Get suggested answer"):
        if not question_text.strip():
            st.warning("Please provide a question.")
        else:
            with st.spinner("Querying AI..."):
                prompt = build_prompt(question_text, choices)
                try:
                    result = query_openai_chat(prompt, model, temp)
                    st.code(result)
                except Exception as e:
                    st.error(f"Error: {e}")

# --- Mode 2: Google Form Link ---
if mode == "Google Form Link":
    form_url = st.text_input("Enter public Google Form link")
    # Restore previously scraped questions if same URL
    if form_url and 'scraped_form_url' in st.session_state and st.session_state['scraped_form_url'] == form_url:
        questions_cached = st.session_state.get('scraped_questions', [])
    else:
        questions_cached = []

    if form_url:
        if st.button("Scrape form"):
            with st.spinner("Scraping form..."):
                qs = scrape_google_form(form_url)
            if not qs:
                st.error("No questions found or form not public.")
                st.session_state.pop('scraped_questions', None)
                st.session_state.pop('scraped_form_url', None)
            else:
                st.session_state['scraped_questions'] = qs
                st.session_state['scraped_form_url'] = form_url
                questions_cached = qs

        if questions_cached:
            st.success(f"Found {len(questions_cached)} questions.")
            perf = st.session_state.get("last_scrape_perf")
            if perf:
                st.caption(f"Scrape method: {perf['method']} in {perf['ms']} ms (cached where possible)")
            # Container for answers cache
            if 'answer_cache' not in st.session_state:
                st.session_state['answer_cache'] = {}
            for i, q in enumerate(questions_cached, start=1):
                st.markdown(f"**Q{i}: {q['question']}**")
                if q['choices']:
                    st.markdown("Choices: " + ", ".join(q['choices']))
                cache_key = f"{form_url}::Q{i}"
                # Show existing answer if cached
                if cache_key in st.session_state['answer_cache']:
                    st.code(st.session_state['answer_cache'][cache_key], language='markdown')
                colA, colB = st.columns([1,4])
                with colA:
                    if st.button("Answer", key=f"ans_btn_{i}"):
                        if not openai.api_key and not os.getenv("OPENAI_API_KEY"):
                            st.error("Missing OPENAI_API_KEY environment variable.")
                        else:
                            with st.spinner("Querying AI..."):
                                prompt = build_prompt(q['question'], q['choices'])
                                result = query_openai_chat(prompt, model, temp)
                                st.session_state['answer_cache'][cache_key] = result
                                st.rerun()
                with colB:
                    if st.button("Regenerate", key=f"regen_btn_{i}"):
                        if not openai.api_key and not os.getenv("OPENAI_API_KEY"):
                            st.error("Missing OPENAI_API_KEY environment variable.")
                        else:
                            with st.spinner("Regenerating..."):
                                prompt = build_prompt(q['question'], q['choices'])
                                result = query_openai_chat(prompt, model, temp)
                                st.session_state['answer_cache'][cache_key] = result
                                st.rerun()
