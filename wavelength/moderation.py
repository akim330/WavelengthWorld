from __future__ import annotations

import re
import string

# MVP-level list. Replace or extend with a fuller moderation system for production.
BANNED_WORDS = {
    "fuck",
    "fucking",
    "shit",
    "bitch",
    "asshole",
    "bastard",
    "cunt",
    "dick",
    "pussy",
    "slut",
    "whore",
    "nigger",
    "nigga",
    "faggot",
    "retard",
}


def normalize_username(username: str) -> str:
    normalized = re.sub(r"\s+", "", username.strip().lower())
    return normalized


def normalize_clue_text(text: str) -> str:
    value = text.strip().lower()
    value = re.sub(r"\s+", " ", value)
    value = value.strip(string.punctuation + " \t\n\r")
    return value


def contains_profanity(text: str) -> bool:
    words = re.findall(r"[a-zA-Z']+", text.lower())
    return any(word in BANNED_WORDS for word in words)


def validate_clue_text(text: str) -> tuple[bool, str | None]:
    if not text or not text.strip():
        return False, "Clue cannot be empty."
    if contains_profanity(text):
        return False, "Please submit a clue without profanity."
    return True, None
