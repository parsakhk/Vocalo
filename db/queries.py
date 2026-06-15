"""
All Supabase query helpers for the bot.
"""
from __future__ import annotations
import random
from collections import defaultdict
from db.client import get_db


# ── Rarity ───────────────────────────────────────────────────────────────────

RARITIES = [
    ("Legendary", 0.03,  "🌟", 1000),
    ("Mythic",    0.10,  "💜",  500),
    ("Rare",      0.15,  "💙",  250),
    ("Common",    1.00,  "⚪",    0),
]

RARITY_ORDER = ["Legendary", "Mythic", "Rare", "Common"]

def roll_rarity() -> str:
    roll = random.random()
    for name, chance, _emoji, _bonus in RARITIES:
        if roll < chance:
            return name
    return "Common"

def rarity_emoji(rarity: str) -> str:
    for name, _, emoji, _bonus in RARITIES:
        if name == rarity:
            return emoji
    return "⚪"


def rarity_bonus(rarity: str) -> int:
    for name, _, _emoji, bonus in RARITIES:
        if name == rarity:
            return bonus
    return 0


# ── Users ────────────────────────────────────────────────────────────────────

def get_user(telegram_id: int) -> dict | None:
    db = get_db()
    res = db.table("users").select("*").eq("telegram_id", telegram_id).execute()
    return res.data[0] if res.data else None


def create_user(telegram_id: int, full_name: str, username: str | None) -> dict:
    db = get_db()
    payload = {
        "telegram_id": telegram_id,
        "full_name":   full_name,
        "username":    username or "",
        "coins":       0,
    }
    res = db.table("users").insert(payload).execute()
    return res.data[0]


def get_or_create_user(telegram_id: int, full_name: str, username: str | None) -> tuple[dict, bool]:
    user = get_user(telegram_id)
    if user:
        return user, False
    return create_user(telegram_id, full_name, username), True


# ── Groups ───────────────────────────────────────────────────────────────────

def is_group_enabled(group_id: int) -> bool:
    db = get_db()
    res = db.table("enabled_groups").select("group_id").eq("group_id", group_id).execute()
    return bool(res.data)


def enable_group(group_id: int, group_name: str, enabled_by: int) -> None:
    db = get_db()
    db.table("enabled_groups").upsert({
        "group_id":   group_id,
        "group_name": group_name,
        "enabled_by": enabled_by,
    }).execute()


# ── Characters ────────────────────────────────────────────────────────────────

def get_random_character() -> dict | None:
    db = get_db()
    res = db.table("characters").select("*").execute()
    if not res.data:
        return None
    return random.choice(res.data)


def match_character_by_guess(guess: str, character: dict) -> bool:
    """
    Returns True if the user's guess matches the character.
    Accepts:
      - Full name          "Naruto Uzumaki"
      - First name only    "Naruto"
      - Last name only     "Uzumaki"
      - Any single word that appears in the name
    All comparisons are case-insensitive.
    """
    guess = guess.strip().lower()
    full  = character["name"].lower()

    if guess == full:
        return True

    # Check each word in the character's name
    for word in full.split():
        if guess == word:
            return True

    return False


# ── Active spawns ─────────────────────────────────────────────────────────────

def set_active_spawn(group_id: int, character_id: int, message_id: int) -> None:
    db = get_db()
    db.table("active_spawns").upsert({
        "group_id":     group_id,
        "character_id": character_id,
        "message_id":   message_id,
    }).execute()


def get_active_spawn(group_id: int) -> dict | None:
    db = get_db()
    res = db.table("active_spawns").select("*").eq("group_id", group_id).execute()
    return res.data[0] if res.data else None


def clear_active_spawn(group_id: int) -> None:
    db = get_db()
    db.table("active_spawns").delete().eq("group_id", group_id).execute()


# ── Inventory ─────────────────────────────────────────────────────────────────

def add_to_inventory(telegram_id: int, character_id: int, base_price: int, char_data: dict = None) -> tuple[int, str]:
    """
    Adds the character to inventory with random rarity, price multiplier,
    and randomized attack/defense within the character's ranges.
    Returns (final_price, rarity).
    """
    rarity       = roll_rarity()
    multiplier   = round(random.uniform(1.0, 1.5), 2)
    caught_price = int(base_price * multiplier)

    # Roll attack and defense from character's ranges
    atk_min = char_data.get("atk_min", 50)  if char_data else 50
    atk_max = char_data.get("atk_max", 150) if char_data else 150
    def_min = char_data.get("def_min", 30)  if char_data else 30
    def_max = char_data.get("def_max", 100) if char_data else 100

    attack  = random.randint(atk_min, atk_max)
    defense = random.randint(def_min, def_max)

    db = get_db()
    db.table("inventory").insert({
        "telegram_id":  telegram_id,
        "character_id": character_id,
        "caught_price": caught_price,
        "rarity":       rarity,
        "attack":       attack,
        "defense":      defense,
    }).execute()

    return caught_price, rarity


def get_inventory(telegram_id: int) -> list[dict]:
    """Returns user's full inventory joined with character info."""
    db = get_db()
    res = (
        db.table("inventory")
        .select("caught_price, rarity, characters(name, anime)")
        .eq("telegram_id", telegram_id)
        .execute()
    )
    return res.data


def format_inventory(items: list[dict], user_name: str) -> str:
    """
    Groups inventory by rarity, then stacks duplicate characters.
    Format: {n}x {Name} ({Anime}) — 💰 {avg_price} coins
    """
    if not items:
        return ""

    # Group by rarity → character name
    # Structure: { rarity: { (name, anime): [prices] } }
    by_rarity: dict[str, dict[tuple, list[int]]] = defaultdict(lambda: defaultdict(list))

    for item in items:
        char   = item.get("characters") or {}
        name   = char.get("name", "Unknown")
        anime  = char.get("anime", "?")
        price  = item.get("caught_price", 0)
        rarity = item.get("rarity", "Common")
        by_rarity[rarity][(name, anime)].append(price)

    total = sum(len(v) for r in by_rarity.values() for v in r.values())
    lines = [f"🗂 *{user_name}'s Inventory* ({total} characters)\n"]

    counter = 1
    for rarity in RARITY_ORDER:
        chars = by_rarity.get(rarity)
        if not chars:
            continue

        emoji = rarity_emoji(rarity)
        lines.append(f"\n{emoji} *{rarity}*")

        for (name, anime), prices in sorted(chars.items()):
            count       = len(prices)
            total_price = sum(prices)
            prefix      = f"{count}x " if count > 1 else ""
            lines.append(f"{counter}. {prefix}*{name}* ({anime}) — 💰 {total_price} coins")
            counter += 1

    return "\n".join(lines)


# ── Profile ───────────────────────────────────────────────────────────────────

def get_profile_stats(telegram_id: int) -> dict:
    """Returns all stats needed for the profile command."""
    db = get_db()

    items = get_inventory(telegram_id)

    # Rarity counts
    rarity_counts = {"Legendary": 0, "Mythic": 0, "Rare": 0, "Common": 0}
    portfolio_value = 0
    anime_counter: dict[str, int] = defaultdict(int)

    rarest_char  = None
    rarest_order = {r: i for i, r in enumerate(RARITY_ORDER)}  # lower = rarer
    rarest_rank  = 999

    for item in items:
        rarity = item.get("rarity", "Common")
        price  = item.get("caught_price", 0)
        char   = item.get("characters") or {}
        anime  = char.get("anime", "?")
        name   = char.get("name", "Unknown")

        rarity_counts[rarity] = rarity_counts.get(rarity, 0) + 1
        portfolio_value += price
        anime_counter[anime] += 1

        rank = rarest_order.get(rarity, 999)
        if rank < rarest_rank:
            rarest_rank  = rank
            rarest_char  = {"name": name, "rarity": rarity}

    favorite_anime = max(anime_counter, key=anime_counter.get) if anime_counter else None
    total          = len(items)

    return {
        "total":          total,
        "rarity_counts":  rarity_counts,
        "portfolio_value": portfolio_value,
        "rarest_char":    rarest_char,
        "favorite_anime": favorite_anime,
    }