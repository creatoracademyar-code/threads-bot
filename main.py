import os
import json
import time
import hashlib
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

# ---------- CONFIG ----------
MAX_RETRIES = 10
LOG_DIR = "logs"
POSTED_LOG = f"{LOG_DIR}/posted_hashes.log"
RUN_LOG = f"{LOG_DIR}/run_history.log"
STATE_FILE = "browser_state/state.json"

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
THREADS_EMAIL = os.environ["THREADS_EMAIL"]
THREADS_PASSWORD = os.environ["THREADS_PASSWORD"]

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """You are a top-tier Threads creator for "Creator Academy".
Write a 3-part Thread. Each part 120-220 words.
Use emotional storytelling, curiosity, strong hook, open loop.
Never sell directly. Pick a random topic from: beginner mistakes, AI business, future predictions, content creation, branding, monetization, hidden opportunities, audience growth, AI myths, creator economy.

Return ONLY valid JSON with a "parts" array of 3 strings.
Example: {"parts": ["Part 1...", "Part 2...", "Part 3..."]}"""

# ---------- LOGGING HELPERS ----------
def ensure_logs():
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    if not os.path.exists("browser_state"):
        os.makedirs("browser_state")

def get_posted_hashes():
    ensure_logs()
    if not os.path.exists(POSTED_LOG):
        return set()
    with open(POSTED_LOG, "r") as f:
        return set(line.strip() for line in f if line.strip())

def save_posted_hash(hash_val):
    ensure_logs()
    with open(POSTED_LOG, "a") as f:
        f.write(f"{hash_val}\n")

def log_run(status, detail=""):
    ensure_logs()
    ts = datetime.utcnow().isoformat()
    with open(RUN_LOG, "a") as f:
        f.write(f"[{ts}] {status}: {detail}\n")

# ---------- GENERATE THREAD (GROQ) ----------
def generate_thread():
    print("📝 Generating thread via Groq...")
    print(f"   Using API key: {GROQ_API_KEY[:10]}...")  # Show first 10 chars to verify
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.3-70b-versatile",  # Updated model name
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Write a new Thread on a random topic."}
        ],
        "temperature": 0.9,
        "max_tokens": 1000
    }
    print("   Sending request to Groq...")
    print(f"   Payload: {json.dumps(payload, indent=2)[:200]}...")
    try:
        resp = requests.post(GROQ_URL, headers=headers, json=payload)
        if resp.status_code != 200:
            print(f"   ❌ Error response: {resp.text}")
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"   ❌ HTTP Error: {e}")
        print(f"   Response body: {e.response.text}")
        raise
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    print(f"   Raw response: {content[:100]}...")
    thread_data = json.loads(content)
    parts = thread_data.get("parts", [])
    if len(parts) < 3:
        raise ValueError(f"Less than 3 parts. Got {len(parts)}")
    print(f"✅ Generated {len(parts)} parts.")
    for i, part in enumerate(parts):
        print(f"   Part {i+1}: {part[:50]}...")
    return parts

# ---------- PUBLISH USING PLAYWRIGHT ----------
def publish_parts_browser(parts):
    print("🌐 Launching browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        print("✅ Browser launched.")

        if os.path.exists(STATE_FILE):
            print("🔄 Loading saved browser session...")
            context = browser.new_context(storage_state=STATE_FILE)
        else:
            print("🔄 No session found. Logging in fresh...")
            context = browser.new_context()
            page = context.new_page()
            page.goto("https://www.threads.net/login")
            print("🔑 Login page loaded. Filling credentials...")
            page.wait_for_selector('input[name="username"]', timeout=10000)
            page.fill('input[name="username"]', THREADS_EMAIL)
            page.fill('input[name="password"]', THREADS_PASSWORD)
            page.click('button[type="submit"]')
            print("⏳ Waiting for login to complete...")
            try:
                page.wait_for_url("https://www.threads.net/*", timeout=30000)
                context.storage_state(path=STATE_FILE)
                print("✅ Session saved successfully!")
            except Exception as e:
                print(f"❌ Login failed: {e}")
                raise Exception("Login failed - likely 2FA or blocked.")

        page = context.new_page()
        print("📄 Navigating to Threads home...")
        page.goto("https://www.threads.net")
        page.wait_for_load_state("networkidle")
        print("✅ Home loaded.")

        print("🔍 Looking for 'New' button...")
        try:
            page.wait_for_selector('div[role="button"]:has-text("New")', timeout=15000)
            page.click('div[role="button"]:has-text("New")')
            print("✅ Clicked 'New' button.")
        except Exception as e:
            print(f"❌ 'New' button not found: {e}")
            raise

        for i, text in enumerate(parts):
            print(f"✍️ Writing part {i+1}/{len(parts)}...")
            try:
                editor = page.locator('div[contenteditable="true"]')
                editor.fill(text)
                print(f"   - Part {i+1} filled.")
            except Exception as e:
                print(f"❌ Could not fill editor: {e}")
                raise

            if i < len(parts) - 1:
                print("   ➕ Clicking 'Add to thread'...")
                try:
                    page.click('button:has-text("Add to thread")')
                    time.sleep(1)
                except Exception as e:
                    print(f"❌ 'Add to thread' button not found: {e}")
                    raise
            else:
                print("📤 Clicking 'Post'...")
                try:
                    page.click('button:has-text("Post")')
                    time.sleep(3)
                    page.wait_for_selector('div[role="button"]:has-text("New")', timeout=10000)
                    print("✅ Post completed.")
                except Exception as e:
                    print(f"❌ 'Post' button or post confirmation failed: {e}")
                    raise

        print("✅ Thread published successfully via browser automation!")
        browser.close()
        return ["browser-post-success"]

# ---------- MAIN ----------
def main():
    ensure_logs()
    posted_hashes = get_posted_hashes()
    print(f"📊 Already posted {len(posted_hashes)} threads.")

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n🔄 Attempt {attempt}/{MAX_RETRIES}")
        try:
            parts = generate_thread()
            full_text = "".join(parts)
            thread_hash = hashlib.sha256(full_text.encode()).hexdigest()

            if thread_hash in posted_hashes:
                raise ValueError("Duplicate thread detected. Retrying.")

            print("🚀 Starting browser publishing...")
            publish_parts_browser(parts)

            save_posted_hash(thread_hash)
            log_run("SUCCESS", f"Posted {len(parts)} parts via browser.")
            print("✅ SUCCESS! Thread posted via browser.")
            return

        except Exception as e:
            error_msg = str(e)
            print(f"❌ Attempt {attempt} failed: {error_msg}")
            log_run(f"RETRY_{attempt}", error_msg)

            if attempt == MAX_RETRIES:
                log_run("FINAL_FAILURE", f"All {MAX_RETRIES} attempts failed. Last error: {error_msg}")
                print("💀 Max retries reached. Giving up.")
                exit(1)
            wait_time = min(2 ** attempt, 300)
            print(f"⏳ Waiting {wait_time}s before retry...")
            time.sleep(wait_time)

if name == "main":
    main()
