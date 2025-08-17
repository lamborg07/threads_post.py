import os
import requests
import random
import html
from bs4 import BeautifulSoup

# ========= Config (env / GitHub Secrets) =========

# Required for Threads API (use a Threads *User Access Token* with scopes like threads_basic, threads_content_publish)
THREADS_USER_ACCESS_TOKEN = os.getenv("THREADS_USER_ACCESS_TOKEN", "")

# Optional post settings
THREADS_VISIBILITY = os.getenv("THREADS_VISIBILITY", "everyone")  # everyone | profiles_you_follow | mentioned_only
THREADS_TOPIC_TAG  = os.getenv("THREADS_TOPIC_TAG", "")           # e.g. "Shopify" (without the #)
THREADS_AUTO_PUBLISH_TEXT = os.getenv("THREADS_AUTO_PUBLISH_TEXT", "false").lower() == "true"

# Content source — either CONTENT_* or Shopify
CONTENT_TITLE      = os.getenv("CONTENT_TITLE")
CONTENT_DESC       = os.getenv("CONTENT_DESC")
CONTENT_HANDLE     = os.getenv("CONTENT_HANDLE")
CONTENT_IMAGE_URL  = os.getenv("CONTENT_IMAGE_URL")

SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "dr-xm.myshopify.com")
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN", "")
NUM_PRODUCTS_TO_FETCH = int(os.getenv("NUM_PRODUCTS_TO_FETCH", "100"))
PRODUCT_HANDLE = os.getenv("PRODUCT_HANDLE")  # optional: force a specific product

CAPTION_LIMIT = int(os.getenv("CAPTION_LIMIT", "280"))  # Threads text limit is higher, but we keep it tidy

# ========= Helpers =========

def _require_threads():
    if not THREADS_USER_ACCESS_TOKEN:
        raise SystemExit("❌ THREADS_USER_ACCESS_TOKEN is missing. See Meta Threads API docs to generate one.")

def _clean_html_to_text(html_content: str, max_chars: int = 3000) -> str:
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content[:max_chars], "lxml")
    return soup.get_text(separator=" ", strip=True)

def _build_text(title: str, desc: str, handle: str | None) -> str:
    title = html.unescape((title or "").strip())
    desc  = html.unescape((desc or "").strip())
    link  = f"https://mydrxm.com/products/{handle}" if handle else ""
    base  = f"{title}\n\n{desc}".strip()
    if len(base) > CAPTION_LIMIT:
        base = base[:CAPTION_LIMIT-3].rstrip() + "..."
    if link:
        base += f"\n\n{link}"
    return base

# ========= Shopify (optional) =========

def _shopify_headers() -> dict:
    if not SHOPIFY_TOKEN:
        raise SystemExit("❌ SHOPIFY_TOKEN missing (or set CONTENT_* envs to bypass Shopify).")
    return {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}

def shopify_fetch_by_handle(store: str, handle: str) -> dict | None:
    url = f"https://{store}/admin/api/2023-01/products.json"
    params = {"limit": 250, "published_status": "published"}
    r = requests.get(url, headers=_shopify_headers(), params=params, timeout=60)
    r.raise_for_status()
    for p in r.json().get("products", []):
        if (p.get("handle") or "").lower() == handle.lower():
            return p
    return None

def shopify_fetch_random(store: str, limit: int = NUM_PRODUCTS_TO_FETCH) -> dict:
    url = f"https://{store}/admin/api/2023-01/products.json"
    params = {"limit": min(250, max(1, limit)), "published_status": "published"}
    r = requests.get(url, headers=_shopify_headers(), params=params, timeout=60)
    r.raise_for_status()
    products = r.json().get("products") or []
    if not products:
        raise SystemExit("❌ Shopify returned no products.")
    return random.choice(products)

# ========= Threads API calls =========
# Official flow: 1) create media container 2) publish it
# Endpoints documented by Meta’s Threads API (graph.threads.net).

def threads_create_media_container_text(text: str) -> str:
    # You can auto-publish text-only posts by passing auto_publish_text=true
    params = {
        "text": text,
        "media_type": "TEXT",
        "reply_control": THREADS_VISIBILITY,
    }
    if THREADS_TOPIC_TAG:
        params["topic_tag"] = THREADS_TOPIC_TAG
    if THREADS_AUTO_PUBLISH_TEXT:
        params["auto_publish_text"] = "true"

    r = requests.post(
        "https://graph.threads.net/me/threads",
        params=params,
        headers={"Authorization": f"Bearer {THREADS_USER_ACCESS_TOKEN}"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["id"]  # creation_id

def threads_create_media_container_image(text: str, image_url: str, alt_text: str | None) -> str:
    params = {
        "text": text,
        "media_type": "IMAGE",
        "image_url": image_url,
        "reply_control": THREADS_VISIBILITY,
    }
    if alt_text:
        params["alt_text"] = alt_text
    if THREADS_TOPIC_TAG:
        params["topic_tag"] = THREADS_TOPIC_TAG

    r = requests.post(
        "https://graph.threads.net/me/threads",
        params=params,
        headers={"Authorization": f"Bearer {THREADS_USER_ACCESS_TOKEN}"},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()["id"]  # creation_id

def threads_publish(creation_id: string) -> str:
    r = requests.post(
        "https://graph.threads.net/me/threads_publish",
        params={"creation_id": creation_id},
        headers={"Authorization": f"Bearer {THREADS_USER_ACCESS_TOKEN}"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["id"]  # the post id

# ========= Main =========

if __name__ == "__main__":
    try:
        _require_threads()

        # Content: prefer CONTENT_* vars, else Shopify
        if CONTENT_TITLE and CONTENT_DESC:
            title = CONTENT_TITLE.strip()
            desc  = CONTENT_DESC.strip()
            handle = (CONTENT_HANDLE or "").strip() or None
            image_url = (CONTENT_IMAGE_URL or "").strip() or None
            print("ℹ️ Using CONTENT_* envs for Threads post.")
        else:
            if PRODUCT_HANDLE:
                print(f"ℹ️ Fetching Shopify product by handle: {PRODUCT_HANDLE}")
                product = shopify_fetch_by_handle(SHOPIFY_STORE, PRODUCT_HANDLE)
                if not product:
                    raise SystemExit(f"❌ No product found for handle '{PRODUCT_HANDLE}'.")
            else:
                print("ℹ️ Fetching a random Shopify product…")
                product = shopify_fetch_random(SHOPIFY_STORE)

            title = product.get("title") or "New Product"
            desc  = _clean_html_to_text(product.get("body_html", ""))
            handle = product.get("handle")
            imgs = product.get("images") or []
            image_url = imgs[0]["src"] if imgs else None
            print(f"✅ Selected: {title} (handle={handle})")

        # Build text
        text = _build_text(title, desc, handle)

        # Create container + publish
        if image_url:
            print("🔹 Creating IMAGE container…")
            creation_id = threads_create_media_container_image(text, image_url, alt_text=title)
            print("🔹 Publishing…")
            post_id = threads_publish(creation_id)
            print(f"✅ Threads image post published: {post_id}")
        else:
            print("🔹 Creating TEXT container…")
            creation_id = threads_create_media_container_text(text)
            if THREADS_AUTO_PUBLISH_TEXT:
                print("✅ Threads text post auto-published")
            else:
                print("🔹 Publishing…")
                post_id = threads_publish(creation_id)
                print(f"✅ Threads text post published: {post_id}")

    except Exception as e:
        print(f"❌ Error: {e}")
        raise
