#!/usr/bin/env python3
import os
import sys
import json
import time
import base64
import logging
import subprocess
import requests
from datetime import datetime, timedelta
from hashlib import sha256

# ---------- CONFIG ----------
REQUIRED_ENV = ["GROQ_API_KEY", "BUFFER_API_KEY", "BUFFER_CHANNEL_ID"]
# POLLINATIONS_API_KEY is optional: if missing, the run continues without a cover image
# instead of failing (see generate_cover_image()).
POSTED_FILE = "posted_threads.json"
LOG_FILE = "run.log"
MAX_RETRIES = 10
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
BUFFER_GRAPHQL_URL = "https://api.buffer.com/graphql"
SCHEDULE_OFFSET_HOURS = 5
SCHEDULE_OFFSET_MINUTES = 17
HISTORY_LIMIT = 20   # number of recent threads to include in the prompt

# ---------- IMAGE CONFIG (Cloudflare Workers AI - free tier) ----------
IMAGES_DIR = "images"
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")
CLOUDFLARE_IMAGE_MODEL = "@cf/black-forest-labs/flux-1-schnell"
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY")   # e.g. "yourname/yourrepo", auto-set by Actions
GITHUB_REF_NAME = os.environ.get("GITHUB_REF_NAME", "main")

# ---------- SETUP LOGGING ----------
logger = logging.getLogger()
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)

fh = logging.FileHandler(LOG_FILE)
fh.setFormatter(formatter)
logger.addHandler(fh)

def check_env():
    missing = [v for v in REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        logger.error(f"Missing required env vars: {', '.join(missing)}")
        sys.exit(1)

check_env()

# ---------- LOAD POSTED THREADS ----------
def load_posted_threads():
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r") as f:
            return json.load(f)
    return []

def save_posted_thread(entry):
    data = load_posted_threads()
    data.append(entry)
    with open(POSTED_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_posted_hashes():
    return {entry["hash"] for entry in load_posted_threads()}

def get_posted_threads_text():
    """Return a formatted string of only the most recent HISTORY_LIMIT threads."""
    entries = load_posted_threads()
    if not entries:
        return "No previous threads have been posted yet."

    # Use only the most recent HISTORY_LIMIT entries
    entries = entries[-HISTORY_LIMIT:]

    text = f"Here are the {len(entries)} most recent threads you have posted:\n\n"
    for i, entry in enumerate(entries, 1):
        text += f"Thread #{i} (posted at {entry.get('timestamp', 'unknown')}):\n"
        for j, post in enumerate(entry.get("posts", []), 1):
            text += f"  Post {j}: {post}\n"
        text += "\n"
    return text

# ---------- LOAD PROMPT ----------
def load_prompt_template():
    with open("prompt.txt", "r", encoding="utf-8") as f:
        return f.read().strip()

PROMPT_TEMPLATE = load_prompt_template()

# ---------- GENERATE THREAD ----------
def generate_thread(history_text):
    system_prompt = PROMPT_TEMPLATE.replace("{{POSTED_THREADS}}", history_text)

    headers = {
        "Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Generate a new Thread now."}
        ],
        "temperature": 0.85,
        "max_tokens": 1500
    }
    resp = requests.post(GROQ_API_URL, headers=headers, json=payload)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    logger.info(f"Groq raw response:\n{content}")

    # Parse JSON
    try:
        posts = json.loads(content)
        if isinstance(posts, list):
            posts = [str(p).strip() for p in posts if str(p).strip()]
            if 2 <= len(posts) <= 6:
                return posts
    except json.JSONDecodeError:
        pass

    # Fallback: try extracting JSON array
    import re
    match = re.search(r'\[.*\]', content, re.DOTALL)
    if match:
        try:
            posts = json.loads(match.group(0))
            if isinstance(posts, list) and 2 <= len(posts) <= 6:
                return posts
        except:
            pass

    logger.warning("Could not parse valid JSON array from Groq response.")
    # Fallback: split by "---" or newlines
    posts = [p.strip() for p in content.split("---") if p.strip()]
    if 2 <= len(posts) <= 6:
        return posts
    posts = [p.strip() for p in content.split("\n\n") if p.strip()]
    if 2 <= len(posts) <= 6:
        return posts

    raise ValueError(f"Could not extract 2-6 posts from response. Got {len(posts)}.")

# ---------- GENERATE COVER IMAGE ----------

def generate_image_prompt(posts):
    """
    Generates a detailed, multi‑line visual prompt (5‑10 sentences) based on the entire thread.
    - Uses all posts (2‑5) as context.
    - NO text, numbers, logos, or letters – the generator can't render them correctly.
    - Focuses on a single scene/metaphor with rich visual description.
    - Outputs 5‑10 sentences covering: subject, setting, colours, lighting, composition,
      atmosphere, style, and textures/materials.
    """
    thread_text = "\n".join([f"Post {i+1}: {p}" for i, p in enumerate(posts)])

    headers = {
        "Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
        "Content-Type": "application/json"
    }

    system_prompt = (
        "You are an expert at creating detailed, evocative visual prompts for AI image generation. "
        "Given a thread of 2‑5 social media posts, imagine a single, powerful scene that captures the "
        "core theme, mood, and message of the entire thread. "
        "Your prompt must be 5‑10 sentences long and include: "
        "- A clear main subject (person, object, animal, or abstract form) "
        "- A specific setting (indoor/outdoor, urban/nature, futuristic/rustic, etc.) "
        "- A distinct colour palette (e.g., warm autumn hues, cool cyberpunk neons, monochrome) "
        "- Detailed lighting (e.g., golden hour, dramatic shadows, soft diffused light) "
        "- Composition and camera angle (e.g., wide shot, close‑up, low‑angle) "
        "- Atmosphere and emotion (e.g., serene, tense, hopeful) "
        "- Texture and materials (e.g., rough concrete, polished metal, wet glass) "
        "- A style hint (e.g., photorealistic, cinematic, oil painting, 3D render) "
        "Crucially, DO NOT include any text, letters, numbers, symbols, or logos – "
        "the image generator cannot render them accurately. "
        "Output ONLY the description, without any extra commentary."
    )

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Thread:\n{thread_text}\n\nCreate a detailed visual description for this thread."}
        ],
        "temperature": 0.7,
        "max_tokens": 400  # enough for 5‑10 sentences
    }

    resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()

def push_image_to_github(filepath):
    """
    Commits and pushes just the generated image file immediately, so it's live
    on GitHub *before* we hand its URL to Buffer. Buffer fetches/validates the
    image URL synchronously when the post is created, not at scheduled time,
    so the file must already exist on GitHub by then.
    """
    try:
        subprocess.run(["git", "config", "user.name", "GitHub Actions Bot"], check=True)
        subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
        subprocess.run(["git", "add", filepath], check=True)

        diff = subprocess.run(["git", "diff", "--staged", "--quiet"])
        if diff.returncode == 0:
            logger.info("Image already committed previously; nothing new to push.")
            return True

        subprocess.run(["git", "commit", "-m", f"Add cover image {os.path.basename(filepath)} [skip ci]"], check=True)
        subprocess.run(["git", "push"], check=True)
        logger.info(f"ðŸ“¤ Pushed {filepath} to GitHub.")
        return True
    except subprocess.CalledProcessError as e:
        logger.warning(f"âš ï¸  Failed to push image to GitHub: {e}")
        return False

def generate_cover_image(posts):
    """
    Generates a free AI cover image via Cloudflare Workers AI (Flux model), saves it
    into the repo, and returns a public CDN URL that Buffer can fetch. Returns None on
    any failure so the thread still posts (text-only) rather than blocking the run.
    """
    try:
        os.makedirs(IMAGES_DIR, exist_ok=True)

        scene = generate_image_prompt(posts)
        """style_suffix = "digital art, minimalist, clean tech aesthetic, soft lighting, no text, no words, no letters" """
        full_prompt = scene
        logger.info(f"ðŸŽ¨ Cover image prompt: {full_prompt}")

        if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
            logger.warning("CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN not set; skipping cover image generation.")
            return None

        cf_url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{CLOUDFLARE_IMAGE_MODEL}"
        cf_headers = {
            "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
            "Content-Type": "application/json"
        }
        cf_payload = {"prompt": full_prompt[:2048]}  # flux-1-schnell max prompt length is 2048 chars

        img_resp = requests.post(cf_url, headers=cf_headers, json=cf_payload, timeout=60)
        img_resp.raise_for_status()
        result = img_resp.json()

        if not result.get("success"):
            raise Exception(f"Cloudflare Workers AI error: {result.get('errors')}")

        image_b64 = result["result"]["image"]
        image_bytes = base64.b64decode(image_b64)

        filename = f"{sha256(full_prompt.encode()).hexdigest()[:16]}.jpg"
        filepath = os.path.join(IMAGES_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(image_bytes)
        logger.info(f"ðŸ–¼ï¸  Saved cover image to {filepath}")

        if not GITHUB_REPOSITORY:
            logger.warning("GITHUB_REPOSITORY env var not set; skipping image attachment.")
            return None

        if not push_image_to_github(filepath):
            logger.warning("Could not push image to GitHub; posting without a cover image.")
            return None

        # raw.githubusercontent.com reflects a fresh push immediately (no CDN cache lag).
        image_url = f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/{GITHUB_REF_NAME}/{IMAGES_DIR}/{filename}"

        # Confirm it's actually fetchable before handing it to Buffer.
        for attempt in range(5):
            check = requests.head(image_url, timeout=15)
            if check.status_code == 200:
                break
            logger.info(f"Image not yet reachable (status {check.status_code}), retrying...")
            time.sleep(2)
        else:
            logger.warning("Image URL never became reachable; posting without a cover image.")
            return None

        logger.info(f"ðŸŒ Public image URL: {image_url}")
        return image_url

    except Exception as e:
        logger.warning(f"âš ï¸  Cover image generation failed, posting without image: {e}")
        return None

# ---------- POST TO BUFFER ----------
def post_to_buffer(posts, image_url=None):
    due_time = datetime.utcnow() + timedelta(hours=SCHEDULE_OFFSET_HOURS, minutes=SCHEDULE_OFFSET_MINUTES)
    due_at = due_time.isoformat() + "Z"
    logger.info(f"Scheduling for: {due_at} UTC")

    first_post = posts[0]

    def post_assets(index):
        # Only the first post in the thread carries the cover image.
        if index == 0 and image_url:
            return [{"image": {"url": image_url}}]
        return []

    thread_entries = [{"text": p, "assets": post_assets(i)} for i, p in enumerate(posts)]

    mutation = """
    mutation CreateThreadedPost($input: CreatePostInput!) {
        createPost(input: $input) {
            ... on PostActionSuccess {
                post {
                    id
                    status
                }
            }
            ... on MutationError {
                message
            }
        }
    }
    """

    post_input = {
        "text": first_post,
        "channelId": os.environ["BUFFER_CHANNEL_ID"],
        "schedulingType": "automatic",
        "mode": "customScheduled",
        "dueAt": due_at,
        "assets": post_assets(0),
        "metadata": {
            "threads": {
                "thread": thread_entries
            }
        }
    }

    variables = {"input": post_input}

    headers = {
        "Authorization": f"Bearer {os.environ['BUFFER_API_KEY']}",
        "Content-Type": "application/json"
    }
    payload = {"query": mutation, "variables": variables}

    resp = requests.post(BUFFER_GRAPHQL_URL, headers=headers, json=payload)
    resp.raise_for_status()
    result = resp.json()

    if "errors" in result:
        raise Exception(f"GraphQL errors: {result['errors']}")

    data = result.get("data", {}).get("createPost", {})
    if "message" in data:
        raise Exception(f"Buffer error: {data['message']}")

    post_id = data.get("post", {}).get("id")
    if not post_id:
        raise Exception(f"Unexpected response: {data}")

    return post_id

# ---------- MAIN ----------
def main():
    # --- Add blank lines and a separator before logging ---
    with open(LOG_FILE, 'a') as f:
        f.write('\n\n')                     # two blank lines
        f.write('=' * 60 + '\n')
        f.write(f'  NEW RUN  {datetime.now().isoformat()}\n')
        f.write('=' * 60 + '\n')

    logger.info("ðŸš€ Starting automation run")

    # Load existing posted hashes
    posted_hashes = get_posted_hashes()
    logger.info(f"ðŸ“š Found {len(posted_hashes)} previously posted threads.")

    # Get only recent history (last 20 threads)
    history_text = get_posted_threads_text()
    logger.info(f"ðŸ“ Will send {min(HISTORY_LIMIT, len(load_posted_threads()))} recent threads to Groq for avoidance.")

    # Retry loop to get a unique thread
    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(f"ðŸ”„ Attempt {attempt}/{MAX_RETRIES} to generate a unique thread.")
        try:
            posts = generate_thread(history_text)
            combined = "".join(posts)
            thread_hash = sha256(combined.encode()).hexdigest()

            if thread_hash in posted_hashes:
                logger.warning("âš ï¸  Duplicate content detected. Retrying...")
                time.sleep(3)
                continue

            logger.info(f"âœ… Unique thread found (hash: {thread_hash[:8]}...)")
            break
        except Exception as e:
            logger.error(f"âŒ Generation error: {e}")
            if attempt == MAX_RETRIES:
                logger.error("Exhausted retries. Exiting.")
                sys.exit(1)
            time.sleep(5)
    else:
        logger.error("Could not generate a unique thread after max retries.")
        sys.exit(1)

    # Log the thread
    logger.info(f"ðŸ“ Generated {len(posts)} posts:")
    for i, p in enumerate(posts, 1):
        logger.info(f"--- Post {i} ---\n{p}")

    # Generate a free AI cover image for the first post
    image_url = generate_cover_image(posts)

    # Post to Buffer
    try:
        post_id = post_to_buffer(posts, image_url=image_url)
        logger.info(f"âœ… Thread scheduled successfully! Buffer Post ID: {post_id}")
    except Exception as e:
        logger.error(f"âŒ Buffer posting failed: {e}")
        sys.exit(1)

    # Save to history
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "hash": thread_hash,
        "posts": posts,
        "buffer_post_id": post_id,
        "image_url": image_url
    }
    save_posted_thread(entry)
    logger.info("ðŸ’¾ Updated posted_threads.json")

    logger.info("âœ… Run completed.")

if __name__ == "__main__":
    main()
