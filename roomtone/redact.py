"""Black-bar redaction for any text that leaves the pipeline (example posts).

Emails, @handles, phone numbers, IBANs, street addresses, and personal names are replaced by a run of
full-block characters, which render as a solid black bar. Links keep their domain only (the site is the
campaign's destination; the path could identify a person). The length of the bar hides the length of
the original. Applied to every source, practice or live, before anything is written to results.json.
"""
import re

BAR = "█"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
HANDLE = re.compile(r"(?<![\w/])@[\w.]{2,}")
PHONE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b")
STREET = re.compile(r"\b\d{1,4}\s+[A-Z][a-zäöüß]+(?:straße|strasse|str\.|street|st\.|road|rd\.|avenue|ave\.|calle|rue)\b|\b[A-Z][a-zäöüß]+(?:straße|strasse|street|road|avenue|calle|rue)\s+\d{1,4}\b", re.I)
URL = re.compile(r"https?://([^\s/]+)(?:/\S*)?")
# names: an honorific or a "my name is / I'm / contact / call" cue followed by capitalised words
NAME_CUE = re.compile(r"((?:\b(?:Mr|Mrs|Ms|Dr|Herr|Frau|Sr|Sra)\.?\s+)|(?:\b(?:my name is|I am|I'm|ich bin|me llamo|contact|call|ask for|reach)\s+))([A-Z][\w'-]+(?:\s+[A-Z][\w'-]+){0,2})")
TWO_CAPS = re.compile(r"\b([A-Z][a-z]{2,})\s+([A-Z][a-z]{2,})\b")
COMMON_CAPS = {"Mail", "Let", "Do", "The", "Wake", "Share", "Machines", "Thousands", "What", "Great", "Every", "Postal", "Fraud", "Guaranteed", "Refs", "Luxury", "Lower", "New", "Top", "Weather", "Earthquake", "Bridged"}


def redact(text: str) -> str:
    if not isinstance(text, str):
        return text
    t = URL.sub(lambda m: m.group(1), text)
    t = EMAIL.sub(lambda m: BAR * 9, t)
    t = IBAN.sub(lambda m: BAR * 10, t)
    t = PHONE.sub(lambda m: BAR * 8, t)
    t = HANDLE.sub(lambda m: BAR * 6, t)
    t = STREET.sub(lambda m: BAR * 9, t)
    t = NAME_CUE.sub(lambda m: m.group(1) + BAR * 7, t)
    t = TWO_CAPS.sub(lambda m: m.group(0) if (m.group(1) in COMMON_CAPS or m.group(2) in COMMON_CAPS or m.start() == 0) else BAR * 7, t)
    return t


def is_redacted(text: str) -> bool:
    return BAR in (text or "")
