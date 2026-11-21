"""Remove only known exercise markings; retain student prose and configuration."""

import re

from .partial_generator import TOMATO_ASCII

SIGNATURE = r"Allen\s+Broodl(?:e)?y\s+Was\s+Here"


def clean_exercise_text(text):
    if not isinstance(text, str):
        return text
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    # Require the entire known artwork. Never delete arbitrary punctuation lines.
    art = TOMATO_ASCII.rsplit("\n", 1)[0]
    pattern = r"\n".join(
        re.escape(line.rstrip()) + r"[ \t]*" for line in art.splitlines()
    )
    cleaned = re.sub(
        pattern + r"(?:\n" + SIGNATURE + r")?\n?", "", normalized, flags=re.IGNORECASE
    )
    cleaned = re.sub(
        r"Tomato:\s*" + SIGNATURE + r"\s*\|\s*", "", cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(r"(?im)^[ \t]*" + SIGNATURE + r"[ \t]*\n?", "", cleaned)
    # Leave all unrelated text byte-for-byte intact when no marker was found.
    return cleaned if cleaned != normalized else text


def merge_notes(current, instructor):
    current = clean_exercise_text(current or "")
    instructor = clean_exercise_text(instructor or "").strip()
    if not instructor or instructor in current:
        return current
    return (
        current.rstrip()
        + ("\n\n" if current.strip() else "")
        + "### Day 4 instructor notes\n"
        + instructor
    )
