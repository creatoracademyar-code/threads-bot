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

# ---------- PUBLISH USING PLAYWRIGHT ----------
def publish_parts_browser(parts):
    print("🌐 Launching browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        print("✅ Browser launched.")

        # Try to load saved session
        if os.path.exists(STATE_FILE):
            print("🔄 Loading saved browser session...")
            context = browser.new_context(storage_state=STATE_FILE)
            page = context.new_page()
            page.goto("https://www.threads.net")
            page.wait_for_load_state("networkidle")
            print("✅ Session loaded.")
        else:
            print("🔄 No session found. Logging in fresh...")
            context = browser.new_context()
            page = context.new_page()

            # Step 1: Go to Threads login page
            print("📄 Navigating to Threads login...")
            page.goto("https://www.threads.net/login")
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            # Step 2: Click "Log in with username instead"
            print("🔍 Looking for 'Log in with username instead' link...")
            try:
                page.click('text="Log in with username instead"')
                print("   ✅ Clicked the link.")
            except Exception as e:
                print(f"   ⚠️ Could not find link: {e}")
                try:
                    page.click('button:has-text("Log in with username instead")')
                    print("   ✅ Clicked the button.")
                except:
                    raise Exception("Could not find 'Log in with username instead' button/link.")

            # Step 3: Fill credentials
            print("🔑 Filling login form...")
            try:
                page.wait_for_selector('input[name="username"]', timeout=10000)
                page.fill('input[name="username"]', THREADS_EMAIL)
                page.fill('input[name="password"]', THREADS_PASSWORD)
                print("   ✅ Credentials filled.")
            except Exception as e:
                print(f"   ❌ Login fields not found: {e}")
                # Try alternative selectors (placeholder text)
                try:
                    page.fill('input[placeholder*="Username"]', THREADS_EMAIL)
                    page.fill('input[placeholder*="Password"]', THREADS_PASSWORD)
                    print("   ✅ Credentials filled using placeholder.")
                except:
                    raise Exception("Could not find login input fields.")

            # Step 4: Click "Log in" button
            print("🔓 Clicking 'Log in' button...")
            page.click('button[type="submit"]')
            time.sleep(2)

            # Step 5: Handle "Save login info" popup
            try:
                if page.locator('button:has-text("Not Now")').is_visible():
                    page.click('button:has-text("Not Now")')
                    print("   ✅ Dismissed save login prompt.")
            except:
                pass

            # Step 6: Wait for redirect to home
            print("⏳ Waiting for login to complete...")
            try:
                page.wait_for_url("https://www.threads.net/*", timeout=30000)
                print("   ✅ Login successful!")
            except Exception as e:
                print(f"   ⚠️ Login issue: {e}")
                if "2fa" in page.url or "challenge" in page.url:
                    raise Exception("2FA required – please approve on your phone or disable 2FA temporarily.")
                else:
                    raise Exception("Login failed – check credentials or approve login on your phone.")

            # Step 7: Save session
            context.storage_state(path=STATE_FILE)
            print("✅ Session saved successfully.")

        # Now we have a logged-in context
        page = context.new_page()
        page.goto("https://www.threads.net")
        page.wait_for_load_state("networkidle")
        print("✅ Threads home loaded.")

        # Step 8: Click the "+" icon (or "New" button) to create a new thread
        print("🔍 Looking for '+' button (new thread)...")
        try:
            # Try the plus icon (most common)
            plus_button = page.locator('svg[aria-label="New post"]').first
            if plus_button.is_visible():
                plus_button.click()
            else:
                # Try the "+" role button
                page.click('div[role="button"]:has-text("+")')
            print("   ✅ Clicked '+' button.")
        except Exception as e:
            print(f"   ⚠️ Could not find '+': {e}")
            try:
                # Fallback to "New" button
                page.click('div[role="button"]:has-text("New")')
                print("   ✅ Clicked 'New' button as fallback.")
            except:
                raise Exception("Could not find new post button.")

        # Step 9: Write each part
        for i, text in enumerate(parts):
            print(f"✍️ Writing part {i+1}/{len(parts)}...")
            try:
                editor = page.locator('div[contenteditable="true"]').first
                editor.fill(text)
                print(f"   ✅ Part {i+1} filled.")
            except Exception as e:
                print(f"   ❌ Could not fill editor: {e}")
                raise

            if i < len(parts) - 1:
                print("   ➕ Clicking 'Add a thread' button...")
                try:
                    page.click('button:has-text("Add a thread")')
                    time.sleep(1)
                except:
                    try:
                        page.click('button:has-text("Add to thread")')
                        time.sleep(1)
                    except Exception as e:
                        print(f"   ⚠️ Could not find 'Add a thread' button: {e}")
                        # Try pressing Enter to add next part (sometimes works)
                        page.keyboard.press("Enter")
                        time.sleep(1)
            else:
                print("📤 Clicking 'Post'...")
                try:
                    page.click('button:has-text("Post")')
                    time.sleep(3)
                    # Wait for the "+" button to reappear (confirms post)
                    page.wait_for_selector('svg[aria-label="New post"]', timeout=10000)
                    print("   ✅ Post completed!")
                except Exception as e:
                    print(f"   ❌ Could not post: {e}")
                    # Try to find if there's a confirmation
                    try:
                        page.wait_for_selector('text="Posted"', timeout=5000)
                        print("   ✅ Post confirmed via 'Posted' text.")
                    except:
                        raise Exception("Failed to confirm post.")

        print("✅ Thread published successfully via browser automation!")
        browser.close()
        return ["browser-post-success"]

# ---------- MAIN LOOP ----------
def main():
    ensure_logs()
    posted_hashes = get_posted_hashes()
    print(f"📊 Already posted {len(posted_hashes)} threads.")

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n🔄 Attempt {attempt}/{MAX_RETRIES}")
        try:
            # Generate thread
            parts = generate_thread()
            full_text = "".join(parts)
            thread_hash = hashlib.sha256(full_text.encode()).hexdigest()

            # Check for duplicate
            if thread_hash in posted_hashes:
                raise ValueError("Duplicate thread detected. Retrying for a fresh one.")

            # Publish
            print("🚀 Starting browser publishing...")
            publish_parts_browser(parts)

            # Save success
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
