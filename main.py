#!/usr/bin/env python3
print("=== main.py started ===")

import os
import json
import time
import hashlib
import requests
from datetime import datetime

print("=== imports: requests done ===")

try:
    import threadspy
    print("=== imports: threadspy done ===")
except ImportError as e:
    print(f"=== ❌ threadspy import failed: {e} ===")
    raise

# ---------- CONFIG ----------
MAX_RETRIES = 10
LOG_DIR = "logs"
POSTED_LOG = f"{LOG_DIR}/posted_hashes.log"
RUN_LOG = f"{LOG_DIR}/run_history.log"

USERNAME = os.environ["THREADS_EMAIL"]
PASSWORD = os.environ["THREADS_PASSWORD"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

print(f"=== Username set: {USERNAME[:3]}... ===")
print(f"=== Groq key set: {GROQ_API_KEY[:10]}... ===")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """You are a top-tier Threads creator for "Creator Academy".
Write a 3-part Thread. Each part 120-220 words.
Use emotional storytelling, curiosity, strong hook, open loop.
Never sell directly. Pick a random topic from: beginner mistakes, AI business, future predictions, content creation, branding, monetization, hidden opportunities, audience growth, AI myths, creator economy.

Return ONLY valid JSON with a "parts" array of 3 strings.
Example: {"parts": ["Part 1...", "Part 2...", "Part 3..."]}"""

# ---------- LOGGING HELPERS ----------
def ensure_logs():
    print("📁 Ensuring logs directory...")
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
        print("   Created logs directory.")
    if not os.path.exists("cache"):
        os.makedirs("cache")
        print("   Created cache directory.")

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

# ---------- GENERATE THREAD VIA GROQ ----------
def generate_thread():
    print("📝 Generating thread via Groq...")
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Write a new Thread on a random topic."}
        ],
        "temperature": 0.9,
        "max_tokens": 1000
    }
    print("   Sending request to Groq...")
    resp = requests.post(GROQ_URL, headers=headers, json=payload)
    print(f"   Response status: {resp.status_code}")
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    thread_data = json.loads(content)
    parts = thread_data.get("parts", [])
    if len(parts) < 3:
        raise ValueError(f"Less than 3 parts. Got {len(parts)}")
    print(f"✅ Generated {len(parts)} parts.")
    return parts

# ---------- PUBLISH USING THREADSPY ----------
def publish_thread_via_api(parts):
    print("🔑 Initializing Threads API...")
    api = threadspy.ThreadsApi(
        USERNAME,
        PASSWORD,
        settings_file="cache/settings.json",
        token_path="cache/threads_token.bin"
    )

    print("🔐 Logging in (using cached session if available)...")
    try:
        login_success = api.login()
        if not login_success:
            raise Exception("Login returned False.")
        print("✅ Login successful!")
    except Exception as e:
        error_msg = str(e)
        # Check if it's a challenge flow
        if "legacy challenge" in error_msg.lower() or "challenge" in error_msg.lower():
            print("⚠️ Instagram triggered a security challenge.")
            print("   This usually happens on the first login from a new IP.")
            print("   Please do the following steps manually, then re-run the workflow:\n")
            print("   1. Open your Threads/Instagram app on your phone.")
            print("   2. You should see a notification about a new login attempt.")
            print("   3. Tap 'It was me' or approve the login.")
            print("   4. The library may have already saved some session data in 'cache/'.")
            print("   5. Re-run this workflow – it should now use the saved token.\n")
            print("   If you have 2FA enabled, you may need to disable it temporarily.")
            print("   For more help, refer to the library's documentation.")
            # Re-raise with a clear message
            raise Exception("Login blocked by challenge. Complete the manual approval on your phone and re-run.")
        else:
            # Other error
            raise

    # Now post
    first_post_id = None
    for i, text in enumerate(parts):
        if i == 0:
            print(f"📝 Creating first part...")
            response = api.create(text=text)
            first_post_id = response.get('id')
            print(f"   ✅ Posted part 1 (ID: {first_post_id})")
        else:
            print(f"📝 Creating part {i+1} as reply...")
            response = api.create(text=text, reply_to=first_post_id)
            print(f"   ✅ Posted part {i+1} (ID: {response.get('id')})")

    print("✅ Thread published successfully!")

# ---------- MAIN ----------
def main():
    print("🚀 main() started")
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
                raise ValueError("Duplicate thread detected.")

            publish_thread_via_api(parts)

            save_posted_hash(thread_hash)
            log_run("SUCCESS", f"Posted {len(parts)} parts.")
            print("✅ SUCCESS! Thread posted.")
            return

        except Exception as e:
            error_msg = str(e)
            print(f"❌ Attempt {attempt} failed: {error_msg}")
            log_run(f"RETRY_{attempt}", error_msg)

            if attempt == MAX_RETRIES:
                log_run("FINAL_FAILURE", f"All attempts failed. Last: {error_msg}")
                print("💀 Max retries reached. Giving up.")
                exit(1)

            wait_time = min(2 ** attempt, 300)
            print(f"⏳ Waiting {wait_time}s...")
            time.sleep(wait_time)

if __name__ == "__main__":
    print("=== Entry point reached ===")
    main()
