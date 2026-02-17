from __future__ import annotations

import re
from typing import Iterable, Iterator, List

# ITU Morse (subset plus punctuation needed by this project)
MORSE_CODE = {
    "A": ".-",
    "B": "-...",
    "C": "-.-.",
    "D": "-..",
    "E": ".",
    "F": "..-.",
    "G": "--.",
    "H": "....",
    "I": "..",
    "J": ".---",
    "K": "-.-",
    "L": ".-..",
    "M": "--",
    "N": "-.",
    "O": "---",
    "P": ".--.",
    "Q": "--.-",
    "R": ".-.",
    "S": "...",
    "T": "-",
    "U": "..-",
    "V": "...-",
    "W": ".--",
    "X": "-..-",
    "Y": "-.--",
    "Z": "--..",
    "0": "-----",
    "1": ".----",
    "2": "..---",
    "3": "...--",
    "4": "....-",
    "5": ".....",
    "6": "-....",
    "7": "--...",
    "8": "---..",
    "9": "----.",
    "/": "-..-.",
    "?": "..--..",
    "=": "-...-",
    ".": ".-.-.-",
    ",": "--..--",
    "-": "-....-",
}

# Prosign pattern: C A V E sent continuously (no inter-letter gap).
PROSIGN_CAVE_PATTERN = MORSE_CODE["C"] + MORSE_CODE["A"] + MORSE_CODE["V"] + MORSE_CODE["E"]
PROSIGN_TOKEN = "<CAVE>"

MORSE_DECODE = {v: k for k, v in MORSE_CODE.items()}
MORSE_DECODE[PROSIGN_CAVE_PATTERN] = PROSIGN_TOKEN

TOKEN_RE = re.compile(r"<[A-Z0-9]+>|[A-Z0-9/?=.,-]+")


def normalize_text(text: str) -> str:
    return " ".join(text.strip().upper().split())


def tokenize_text(text: str) -> List[str]:
    return TOKEN_RE.findall(normalize_text(text))


def iter_token_chars(token: str) -> Iterator[str]:
    if token.startswith("<") and token.endswith(">") and len(token) > 2:
        yield from token[1:-1]
        return
    for ch in token:
        yield ch


def token_to_morse_letters(token: str) -> List[str]:
    letters: List[str] = []
    for ch in iter_token_chars(token):
        if ch not in MORSE_CODE:
            continue
        letters.append(MORSE_CODE[ch])
    return letters


def collapse_cave_tokens(tokens: Iterable[str]) -> List[str]:
    """
    Convert 'CAVE' literals into prosign token in text-level flows.
    This does not try to infer timing; timing-based decode happens in decoder.
    """
    out: List[str] = []
    for tok in tokens:
        if tok == "CAVE":
            out.append(PROSIGN_TOKEN)
        else:
            out.append(tok)
    return out
