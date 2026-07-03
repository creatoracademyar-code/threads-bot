#!/usr/bin/env python3
import os
import sys
import json
import requests
from datetime import datetime, timedelta

# ---------- REQUIRED ENVIRONMENT VARIABLES ----------
REQUIRED_ENV = ["GROQ_API_KEY", "BUFFER_API_KEY", "BUFFER_CHANNEL_ID"]

def check_env():
    missing = [var for var in REQUIRED_ENV if not os.environ.get(var)]
    if missing:
        print(f"❌ Missing required environment variables: {', '.join(missing)}")
        print("   Please set them before running.")
        print("   For local testing: export VAR=value")
        print("   For GitHub Actions: add them as repository secrets.")
        sys.exit(1)

check_env()

# ---------- API ENDPOINTS ----------
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"          # Groq's latest model
BUFFER_GRAPHQL_URL = "https://api.buffer.com/graphql"

# ---------- READ PROMPT ----------
def load_prompt():
    with open("prompt.txt", "r", encoding="utf-8") as f:
        return f.read().strip()

SYSTEM_PROMPT = load_prompt()

# ---------- GENERATE THREAD ----------
def generate_thread():
    headers = {
        "Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Generate one Thread now."}
        ],
        "temperature": 0.8,
        "max_tokens": 1200
    }
    resp = requests.post(GROQ_API_URL, headers=headers, json=payload)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    print(f"\n📝 Groq raw response:\n{content}\n")

    # Try JSON
    try:
        posts = json.loads(content)
        if isinstance(posts, list):
            posts = [str(p).strip() for p in posts if str(p).strip()]
            if len(posts) >= 2:
                return posts[:4]
    except json.JSONDecodeError:
        pass

    # Fallback split
    posts = [p.strip() for p in content.split("---") if p.strip()]
    if len(posts) < 2:
        posts = [p.strip() for p in content.split("\n\n") if p.strip()]
    return posts[:4]

# ---------- POST TO BUFFER (with scheduling 5 min from now) ----------
def post_to_buffer(posts):
    due_time = datetime.utcnow() + timedelta(minutes=5)
    due_at = due_time.isoformat() + "Z"
    print(f"⏰ Scheduled for: {due_at} UTC")

    first_post = posts[0] if posts else ""
    thread_entries = [{"text": p} for p in posts]

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

    variables = {
        "input": {
            "text": first_post,
            "channelId": os.environ["BUFFER_CHANNEL_ID"],
            "schedulingType": "automatic",
            "mode": "customScheduled",
            "dueAt": due_at,
            "metadata": {
                "threads": {
                    "thread": thread_entries
                }
            }
        }
    }

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
    print(f"🚀 Starting at {datetime.now().isoformat()}")

    posts = generate_thread()
    if not posts:
        print("❌ No posts generated. Exiting.")
        sys.exit(1)

    print(f"✅ Generated {len(posts)} posts:")
    for i, p in enumerate(posts, 1):
        print(f"--- Post {i} ---\n{p}\n")

    try:
        post_id = post_to_buffer(posts)
        print(f"✅ Thread scheduled successfully! Buffer Post ID: {post_id}")
    except Exception as e:
        print(f"❌ Failed to post: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
