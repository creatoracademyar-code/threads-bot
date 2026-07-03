#!/usr/bin/env python3
import os
import sys
import json
import requests
from datetime import datetime, timedelta

# ---------- API ENDPOINTS ----------
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROK_MODEL = "llama-3.3-70b-versatile"  # or "grok-2"
BUFFER_GRAPHQL_URL = "https://api.buffer.com/graphql"   # correct endpoint

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
        "model": GROK_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Generate one Thread now."}
        ],
        "temperature": 0.8,
        "max_tokens": 1200
    }
    resp = requests.post(GROK_API_URL, headers=headers, json=payload)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    print(f"\n📝 Grok raw response:\n{content}\n")

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

# ---------- POST TO BUFFER (with scheduling) ----------
def post_to_buffer(posts):
    # Calculate due time: now + 5 minutes (UTC)
    due_time = datetime.utcnow() + timedelta(minutes=5)
    due_at = due_time.isoformat() + "Z"   # e.g., "2026-07-05T10:33:00.000Z"
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
            "schedulingType": "automatic",          # automatic scheduling
            "mode": "customScheduled",              # we are scheduling
            "dueAt": due_at,                        # 5 minutes from now
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
