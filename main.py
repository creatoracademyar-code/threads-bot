import os
import json
import time
import hashlib
import requests
from datetime import datetime
import threadspy

# ---------- CONFIG ----------
MAX_RETRIES = 10
LOG_DIR = "logs"
POSTED_LOG = f"{LOG_DIR}/posted_hashes.log"
RUN_LOG = f"{LOG_DIR}/run_history.log"

# Threads credentials from GitHub Secrets
USERNAME = os.environ["THREADS_EMAIL"]
PASSWORD = os.environ["THREADS_PASSWORD"]

# Groq API key from GitHub Secrets
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# System prompt for Groq (generates a 3‑part Thread)
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
    resp = requests.post(GROQ_URL, headers=headers, json=payload)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    thread_data = json.loads(content)
    parts = thread_data.get("parts", [])
    if len(parts) < 3:
        raise ValueError(f"Less than 3 parts. Got {len(parts)}")
    print(f"✅ Generated {len(parts)} parts.")
    return parts

# ---------- PUBLISH USING THREADSPY (NO BROWSER) ----------
def publish_thread_via_api(parts):
    """
    Logs in once (or uses cached token) and posts the thread as a chain of replies.
    """
    print("🔑 Initializing Threads API...")
    # The library will store/load token from these paths automatically
    api = threadspy.ThreadsApi(
        USERNAME,
        PASSWORD,
        settings_file="cache/settings.json",
        token_path="cache/threads_token.bin"
    )

    print("🔐 Logging in (or using cached session)...")
    login_success = api.login()
    if not login_success:
        raise Exception("Login failed. Check credentials or approve on phone (first run only).")

    print("✅ Login successful!")

    # Create the thread (first post, then replies)
    first_post_id = None
    for i, text in enumerate(parts):
        if i == 0:
            print(f"📝 Creating first part...")
            response = api.create(text=text)
            first_post_id = response.get('id')
            print(f"   ✅ Posted part 1 (ID: {first_post_id})")
        else:
            print(f"📝 Creating part {i+1} as reply...")
            # reply to the previous post (for a linear chain)
            response = api.create(text=text, reply_to=first_post_id)
            print(f"   ✅ Posted part {i+1} (ID: {response.get('id')})")

    print("✅ Thread published successfully!")

# ---------- MAIN LOOP (with retries and duplicate check) ----------
def main():
    ensure_logs()
    posted_hashes = get_posted_hashes()
    print(f"📊 Already posted {len(posted_hashes)} threads.")

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n🔄 Attempt {attempt}/{MAX_RETRIES}")
        try:
            # 1. Generate thread content
            parts = generate_thread()
            full_text = "".join(parts)
            thread_hash = hashlib.sha256(full_text.encode()).hexdigest()

            # 2. Check for duplicates
            if thread_hash in posted_hashes:
                raise ValueError("Duplicate thread detected. Retrying for a fresh one.")

            # 3. Publish using threadspy
            publish_thread_via_api(parts)

            # 4. Save success
            save_posted_hash(thread_hash)
            log_run("SUCCESS", f"Posted {len(parts)} parts via API.")
            print("✅ SUCCESS! Thread posted.")
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

if __name__ == "__main__":
    main()
