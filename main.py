import os
import json
import time
import hashlib
import requests
from datetime import datetime

# ---------- CONFIG ----------
MAX_RETRIES = 10
LOG_DIR = "logs"
POSTED_LOG = f"{LOG_DIR}/posted_hashes.log"
RUN_LOG = f"{LOG_DIR}/run_history.log"

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
THREADS_TOKEN = os.environ["THREADS_ACCESS_TOKEN"]
THREADS_USER_ID = os.environ["THREADS_USER_ID"]

BASE_URL = "https://graph.threads.net/v1.0"
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

# ---------- GENERATE THREAD (GROQ – FREE) ----------
def generate_thread():
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama3-70b-8192",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Write a new Thread on a random topic."}
        ],
        "temperature": 0.9,
        "response_format": {"type": "json_object"}
    }
    resp = requests.post(GROQ_URL, headers=headers, json=payload)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    thread_data = json.loads(content)
    parts = thread_data.get("parts", [])
    if len(parts) < 3:
        raise ValueError(f"Less than 3 parts. Got {len(parts)}")
    return parts

# ---------- PUBLISH THREAD ----------
def publish_parts(parts):
    published_ids = []
    for i, text in enumerate(parts):
        payload = {"media_type": "TEXT", "text": text, "access_token": THREADS_TOKEN}
        if i > 0:
            payload["reply_to_id"] = published_ids[-1]

        create_resp = requests.post(f"{BASE_URL}/{THREADS_USER_ID}/threads", data=payload)
        create_resp.raise_for_status()
        creation_id = create_resp.json()["id"]

        publish_resp = requests.post(
            f"{BASE_URL}/{THREADS_USER_ID}/threads_publish",
            data={"creation_id": creation_id, "access_token": THREADS_TOKEN}
        )
        publish_resp.raise_for_status()
        pid = publish_resp.json()["id"]
        published_ids.append(pid)
        time.sleep(2)
    return published_ids

# ---------- MAIN LOOP ----------
def main():
    ensure_logs()
    posted_hashes = get_posted_hashes()

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"🔄 Attempt {attempt}/{MAX_RETRIES}")
        try:
            parts = generate_thread()
            full_text = "".join(parts)
            thread_hash = hashlib.sha256(full_text.encode()).hexdigest()

            if thread_hash in posted_hashes:
                raise ValueError("Duplicate thread detected. Retrying.")

            thread_ids = publish_parts(parts)
            save_posted_hash(thread_hash)
            log_run("SUCCESS", f"Posted {len(parts)} parts. IDs: {thread_ids}")
            print(f"✅ SUCCESS! Thread IDs: {thread_ids}")
            return
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Attempt {attempt} failed: {error_msg}")
            log_run(f"RETRY_{attempt}", error_msg)

            if attempt == MAX_RETRIES:
                log_run("FINAL_FAILURE", f"All {MAX_RETRIES} attempts failed. Last error: {error_msg}")
                print(f"💀 Max retries reached. Giving up.")
                exit(1)

            wait_time = min(2 ** attempt, 300)
            print(f"⏳ Waiting {wait_time}s before retry...")
            time.sleep(wait_time)

if name == "main":
    main()
