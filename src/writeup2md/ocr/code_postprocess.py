"""Code-aware post-processing for OCR output (TASK_11).

These operations are STRUCTURAL ONLY. They never invent or repair code
semantically. Allowed operations:

- split clearly-merged tokens at known keyword boundaries
  (`importrequests` → `import requests`);
- normalize fullwidth punctuation to ASCII when the surrounding context
  is code;
- recover indentation from bracket/colon structure (best-effort).

Forbidden (per spec "Never silently invent, complete or repair code"):

- looking up missing tokens in a language model;
- auto-fixing syntax errors;
- completing partial identifiers;
- replacing unknown characters with "likely" substitutes;
- merging or splitting lines based on language semantics.
"""

from __future__ import annotations

import re


# Conservative keyword dictionary for space-merge splitting. We only split
# when BOTH the prefix and the suffix are known keywords/identifiers, so we
# never invent a token boundary that produces a non-word.
#
# Each entry is (prefix, suffix, replacement) where replacement is the
# correctly-spaced form. We require that the prefix is followed immediately
# (no whitespace) by the suffix in the input text.
_SPLIT_RULES: list[tuple[str, str, str]] = [
    # Python imports.
    ("import", "requests", "import requests"),
    ("import", "os", "import os"),
    ("import", "sys", "import sys"),
    ("import", "json", "import json"),
    ("import", "re", "import re"),
    ("import", "subprocess", "import subprocess"),
    ("import", "hashlib", "import hashlib"),
    ("import", "base64", "import base64"),
    ("import", "datetime", "import datetime"),
    ("import", "urllib", "import urllib"),
    ("import", "socket", "import socket"),
    ("import", "struct", "import struct"),
    ("import", "threading", "import threading"),
    ("from", "requests", "from requests"),
    ("from", "os", "from os"),
    ("from", "sys", "from sys"),
    ("from", "json", "from json"),
    ("from", "re", "from re"),
    ("from", "subprocess", "from subprocess"),
    ("from", "hashlib", "from hashlib"),
    ("from", "base64", "from base64"),
    ("from", "datetime", "from datetime"),
    ("from", "urllib", "from urllib"),
    ("from", "socket", "from socket"),
    ("from", "struct", "from struct"),
    ("from", "threading", "from threading"),
    # Python defs.
    ("def", "main", "def main"),
    ("def", "run", "def run"),
    ("def", "login", "def login"),
    ("def", "exploit", "def exploit"),
    ("def", "parse", "def parse"),
    ("def", "send", "def send"),
    ("def", "recv", "def recv"),
    ("def", "encrypt", "def encrypt"),
    ("def", "decrypt", "def decrypt"),
    ("def", "encode", "def encode"),
    ("def", "decode", "def decode"),
    ("def", "build", "def build"),
    ("def", "execute", "def execute"),
    ("class", "Exploit", "class Exploit"),
    ("class", "Client", "class Client"),
    ("class", "Server", "class Server"),
    ("class", "Parser", "class Parser"),
    ("class", "Config", "class Config"),
    # Print / return.
    ("print", "(", "print("),
    ("return", "response", "return response"),
    ("return", "result", "return result"),
    ("return", "data", "return data"),
    ("return", "value", "return value"),
    ("return", "True", "return True"),
    ("return", "False", "return False"),
    ("return", "None", "return None"),
    # bash.
    ("sudo", "apt", "sudo apt"),
    ("sudo", "pip", "sudo pip"),
    ("sudo", "npm", "sudo npm"),
    ("sudo", "systemctl", "sudo systemctl"),
    ("sudo", "docker", "sudo docker"),
    ("curl", "http", "curl http"),
    ("curl", "-X", "curl -X"),
    ("curl", "-H", "curl -H"),
    ("curl", "-d", "curl -d"),
    ("wget", "http", "wget http"),
    ("npm", "install", "npm install"),
    ("pip", "install", "pip install"),
    ("apt", "install", "apt install"),
    ("apt", "update", "apt update"),
    ("apt", "upgrade", "apt upgrade"),
    # Common shell patterns.
    ("cd", "/", "cd /"),
    ("ls", "-l", "ls -l"),
    ("ls", "-la", "ls -la"),
    ("cat", "/etc", "cat /etc"),
    ("grep", "-r", "grep -r"),
    ("grep", "-i", "grep -i"),
    ("chmod", "+x", "chmod +x"),
    ("chmod", "755", "chmod 755"),
    ("chmod", "644", "chmod 644"),
    ("mkdir", "-p", "mkdir -p"),
    ("rm", "-rf", "rm -rf"),
    # HTTP.
    ("GET", "/api", "GET /api"),
    ("POST", "/api", "POST /api"),
    ("PUT", "/api", "PUT /api"),
    ("DELETE", "/api", "DELETE /api"),
    ("Content-Type:", "application", "Content-Type: application"),
    ("Authorization:", "Bearer", "Authorization: Bearer"),
    ("User-Agent:", "Mozilla", "User-Agent: Mozilla"),
    # Diff.
    ("diff", "--git", "diff --git"),
    ("index", "0000000", "index 0000000"),
]


def split_space_merged_tokens(text: str, language: str | None = None) -> tuple[str, list[str]]:
    """Split tokens that were merged by OCR at known keyword boundaries.

    Returns (corrected_text, transformations). Only splits where BOTH the
    prefix and suffix are known keywords. Never invents a token boundary.
    """
    if not text:
        return text, []
    transformations: list[str] = []
    out = text
    for prefix, suffix, replacement in _SPLIT_RULES:
        merged = prefix + suffix
        # We require the merged form to appear as a token (not as a substring
        # of a larger identifier) — so we check word boundaries. The prefix
        # must be at a word start, and the suffix must end at a word end.
        # We use a regex that matches the merged form not preceded/followed
        # by a word character.
        pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(merged) + r"(?![A-Za-z0-9_])")
        new_out, n = pattern.subn(replacement, out)
        if n > 0:
            out = new_out
            transformations.append(f"split:{merged}->{replacement}")
    return out, transformations


# Fullwidth → ASCII punctuation mapping. Only applied in code contexts
# (detected via presence of common code keywords/structure).
_FULLWIDTH_MAP: dict[str, str] = {
    "，": ",",
    "。": ".",
    "：": ":",
    "；": ";",
    "！": "!",
    "？": "?",
    "（": "(",
    "）": ")",
    "［": "[",
    "］": "]",
    "｛": "{",
    "｝": "}",
    "＂": '"',
    "＇": "'",
    "＜": "<",
    "＞": ">",
    "＝": "=",
    "＋": "+",
    "－": "-",
    "＊": "*",
    "／": "/",
    "＼": "\\",
    "＆": "&",
    "｜": "|",
    "＃": "#",
    "％": "%",
    "＠": "@",
    "＄": "$",
    "＾": "^",
    "～": "~",
    "｀": "`",
}


def _looks_like_code(text: str) -> bool:
    """Heuristic: does this text look like code (vs natural prose)?

    Used to decide whether fullwidth punctuation normalization is safe.
    """
    if not text:
        return False
    code_indicators = 0
    for kw in ("import", "def ", "class ", "function", "var ", "let ", "const ",
               "printf", "echo ", "print", "return ", "if ", "for ", "while ",
               "GET ", "POST ", "HTTP/", "@@", "$ ", "> ",
               # HTTP headers / config keys.
               "Content-Type:", "Content-Length:", "Authorization:", "User-Agent:",
               "Accept:", "Host:", "Cookie:", "Set-Cookie:", "Location:",
               "Server:", "Date:", "Cache-Control:", "X-",
               # Config file markers.
               ".yml", ".yaml", ".json", ".toml", ".ini", ".conf"):
        if kw in text:
            code_indicators += 1
    # Bracket density.
    brackets = sum(1 for c in text if c in "()[]{}=;:")
    if brackets >= 3:
        code_indicators += 1
    # Key-value pattern (e.g. "Content-Type: application/json"). Accept both
    # ASCII and fullwidth colons so a fullwidth-colon header is still
    # detected as code.
    if re.search(r"^[A-Za-z][A-Za-z0-9\-]*\s*[:：=]\s*\S", text, re.MULTILINE):
        code_indicators += 1
    return code_indicators >= 1


def normalize_fullwidth_punct(text: str) -> tuple[str, list[str]]:
    """Normalize fullwidth punctuation to ASCII in code contexts.

    Returns (corrected_text, transformations). If the text doesn't look
    like code, no normalization is applied (we don't want to mangle
    natural-language Chinese text).
    """
    if not text or not _looks_like_code(text):
        return text, []
    out = []
    changed = 0
    for ch in text:
        if ch in _FULLWIDTH_MAP:
            out.append(_FULLWIDTH_MAP[ch])
            changed += 1
        else:
            out.append(ch)
    if changed == 0:
        return text, []
    return "".join(out), [f"fullwidth_punct_normalized:{changed}chars"]


def recover_indentation(text: str, language: str | None = None) -> tuple[str, list[str]]:
    """Best-effort indentation recovery from bracket/colon structure.

    Conservative rules:
    - After a line ending with `:`, increase indent by 4 spaces (Python).
    - After a line ending with `{`, increase indent by 4 spaces (JS/C/Go).
    - Before a line containing `}` or `)`, decrease indent first.
    - Empty lines are left empty.
    - Lines that already have leading whitespace are NOT re-indented.

    This never rewrites existing indentation; it only ADDS indentation to
    lines that have none when the structure clearly calls for it.
    """
    if not text:
        return text, []
    lines = text.split("\n")
    out: list[str] = []
    indent = 0
    transformations: list[str] = []
    for ln in lines:
        stripped = ln.lstrip()
        if not stripped:
            out.append("")
            continue
        # If the line already has leading whitespace, respect it.
        if ln[:1] in (" ", "\t"):
            out.append(ln)
            continue
        # Closing bracket: dedent first.
        if stripped[:1] in ("}", ")", "]"):
            indent = max(0, indent - 4)
        # Apply current indent.
        if indent > 0:
            new_ln = " " * indent + stripped
            if new_ln != ln:
                transformations.append("indent_recovered")
            out.append(new_ln)
        else:
            out.append(stripped)
        # After-colon / after-open-brace: indent next line.
        if stripped.endswith(":") or stripped.endswith("{"):
            indent += 4
        elif stripped.endswith("(") and language == "python":
            # Python line continuation — keep indent for now.
            pass
    if not transformations:
        return text, []
    return "\n".join(out), transformations
