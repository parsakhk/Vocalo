"""
fetch_images.py
---------------
Looks up every character in your Supabase `characters` table on AniList,
finds their image URL, and updates the record.

Usage:
    python fetch_images.py

Requirements (already in requirements.txt):
    pip install supabase python-dotenv requests
"""

import time
import requests
from dotenv import load_dotenv
from db.client import get_db

load_dotenv()

ANILIST_API = "https://graphql.anilist.co"

QUERY = """
query ($name: String) {
  Character(search: $name) {
    id
    name {
      full
    }
    image {
      large
    }
  }
}
"""


def search_character(name: str) -> dict | None:
    """Search AniList for a character by name. Returns {name, image_url} or None."""
    try:
        response = requests.post(
            ANILIST_API,
            json={"query": QUERY, "variables": {"name": name}},
            timeout=10,
        )
        if response.status_code == 429:
            # Rate limited — wait and retry once
            retry_after = int(response.headers.get("Retry-After", 60))
            print(f"  ⏳ Rate limited. Waiting {retry_after}s...")
            time.sleep(retry_after)
            response = requests.post(
                ANILIST_API,
                json={"query": QUERY, "variables": {"name": name}},
                timeout=10,
            )

        data = response.json()
        char = data.get("data", {}).get("Character")
        if not char:
            return None

        return {
            "anilist_name": char["name"]["full"],
            "image_url":    char["image"]["large"],
        }

    except Exception as e:
        print(f"  ❌ Request error: {e}")
        return None


def main():
    db = get_db()

    print("📦 Fetching characters from Supabase...")
    res = db.table("characters").select("id, name, image_url").execute()
    characters = res.data

    if not characters:
        print("No characters found in the database.")
        return

    print(f"Found {len(characters)} characters.\n")

    updated = 0
    skipped = 0
    failed  = 0

    for char in characters:
        cid   = char["id"]
        name  = char["name"]
        print(f"🔍 Searching: {name}")

        result = search_character(name)

        if not result:
            print(f"  ⚠️  Not found on AniList — skipping.\n")
            failed += 1
            continue

        image_url = result["image_url"]
        anilist_name = result["anilist_name"]

        if image_url == char.get("image_url"):
            print(f"  ✅ Already up to date ({anilist_name})\n")
            skipped += 1
            continue

        db.table("characters").update({"image_url": image_url}).eq("id", cid).execute()
        print(f"  ✅ Updated → {anilist_name}")
        print(f"     🖼  {image_url}\n")
        updated += 1

        # Be polite to AniList's API — 0.6s between requests
        time.sleep(0.6)

    print("─" * 40)
    print(f"Done! ✅ Updated: {updated} | ⏭ Skipped: {skipped} | ❌ Failed: {failed}")


if __name__ == "__main__":
    main()