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

# ---------- PUBLISH USING PLAYWRIGHT (Instagram login) ----------
def publish_parts_browser(parts):
    print("🌐 Launching browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        print("✅ Browser launched.")

        context_options = {}
        if os.path.exists(STATE_FILE):
            print("🔄 Loading saved browser session...")
            context = browser.new_context(storage_state=STATE_FILE)
        else:
            print("🔄 No session found. Logging in fresh...")
            context = browser.new_context()
            page = context.new_page()

            # Go directly to Instagram login (Threads uses Instagram auth)
            print("🔑 Navigating to Instagram login...")
            page.goto("https://www.instagram.com/accounts/login/")
            page.wait_for_load_state("networkidle")

            # Try to find the login form – Instagram uses different selectors
            print("⏳ Waiting for login form...")
            try:
                # Wait for username field
                page.wait_for_selector('input[name="username"]', timeout=15000)
                print("✅ Username field found.")
                page.fill('input[name="username"]', THREADS_EMAIL)
                page.fill('input[name="password"]', THREADS_PASSWORD)
                # Click login button
                page.click('button[type="submit"]')
            except Exception as e:
                # Maybe it's the "Save login info" prompt – we can handle later
                print(f"⚠️ Could not find standard login fields: {e}")
                raise

            # Wait for login to complete (redirect to main page)
            try:
                page.wait_for_url("https://www.instagram.com/*", timeout=30000)
                print("✅ Instagram login successful.")
            except:
                # Might need to handle "Not Now" for save info
                try:
                    page.click('button:has-text("Not Now")')
                    page.wait_for_url("https://www.instagram.com/*", timeout=10000)
                except:
                    pass

            # Now navigate to Threads
            print("📄 Navigating to Threads...")
            page.goto("https://www.threads.net")
            page.wait_for_load_state("networkidle")

            # Save session for future runs
            context.storage_state(path=STATE_FILE)
            print("✅ Session saved successfully.")

        # Now we have a logged-in context, open a new page
        page = context.new_page()
        page.goto("https://www.threads.net")
        page.wait_for_load_state("networkidle")
        print("✅ Threads home loaded.")

        # Click New Post button
        print("🔍 Looking for 'New' button...")
        try:
            # Try different selectors for "New" button
            new_button = page.locator('div[role="button"]:has-text("New")').first
            if new_button.is_visible():
                new_button.click()
            else:
                # Fallback: try the plus icon or compose button
                page.click('svg[aria-label="New post"]')
            print("✅ Clicked 'New' button.")
        except Exception as e:
            print(f"❌ Could not find New button: {e}")
            raise

        # Wait for the compose window
        try:
            page.wait_for_selector('div[contenteditable="true"]', timeout=10000)
        except:
            # Sometimes it's a different container
            pass

        # Write each part
        for i, text in enumerate(parts):
            print(f"✍️ Writing part {i+1}/{len(parts)}...")
            try:
                # Find editable div
                editor = page.locator('div[contenteditable="true"]').first
                editor.fill(text)
                print(f"   - Part {i+1} filled.")
            except Exception as e:
                print(f"❌ Could not fill editor: {e}")
                raise

            if i < len(parts) - 1:
                print("   ➕ Adding next part...")
                try:
                    # Click the "Add to thread" button (maybe plus icon)
                    page.click('button:has-text("Add to thread")')
                    time.sleep(1)
                except:
                    # Try alternative
                    page.click('svg[aria-label="Add to thread"]')
                    time.sleep(1)
            else:
                print("📤 Posting...")
                try:
                    page.click('button:has-text("Post")')
                    time.sleep(3)
                    # Wait for post to be confirmed
                    page.wait_for_selector('div[role="button"]:has-text("New")', timeout=10000)
                    print("✅ Post completed.")
                except Exception as e:
                    print(f"❌ Could not post: {e}")
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

if __name__ == "__main__":
    main()
