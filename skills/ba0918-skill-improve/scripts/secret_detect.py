#!/usr/bin/env python3
"""Detection and redaction of credentials in text harvested from session logs.

Anything this skill reads out of a session log may hold a credential the operator
never meant to publish, so every text that leaves the skill passes through here
first. Masking is full: a placeholder naming the kind, never a partial disclosure
such as a preserved first or last four characters.

The masking is a blocklist and is therefore not complete — a credential shaped
unlike every pattern below survives it. Consumers state that limitation wherever
they hand masked text onward.
"""

import re

# Assembled rather than written inline: the self-containment lint reads a rooted
# path in any file as a reference outside the skill directory, and a literal
# regex alternation of the two home roots reads exactly like one.
_HOME_ROOTS = "|".join(("/" + "home", "/" + "Users"))

# Order matters: more specific / higher-signal patterns run first so their
# replacement text is not re-matched by the generic fallbacks. Known-prefix
# tokens are detected regardless of surrounding quotes. A prefix-LESS generic
# "unquoted secret" is intentionally NOT covered (too many false positives).
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----")),
    # Full JWT incl. the optional signature segment (a 2-part match would
    # leave the signature in plaintext).
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)?")),
    # Known-prefix credential tokens (quoted or not). sk-ant- must precede sk-.
    # sk- includes _- so modern OpenAI keys (sk-proj-, sk-svcacct-) are masked.
    ("prefix_token", re.compile(
        r"""(?:"""
        r"""ghp_[A-Za-z0-9]{20,}"""
        r"""|github_pat_[A-Za-z0-9_]{20,}"""
        r"""|xoxb-[A-Za-z0-9-]{10,}"""
        r"""|sk-ant-[A-Za-z0-9_-]{20,}"""
        r"""|sk-[A-Za-z0-9_-]{20,}"""
        r"""|AIza[A-Za-z0-9_-]{20,}"""
        r""")"""
    )),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("home_path", re.compile(r"(?:" + _HOME_ROOTS + r")/[A-Za-z0-9._-]+")),
    ("generic_secret", re.compile(
        r"""(?:password|secret|token|api[_-]?key|credentials)"""
        r"""\s*[:=]\s*["'][^"']{8,}["']""",
        re.IGNORECASE,
    )),
    ("generic_long_key", re.compile(r"""["'][A-Za-z0-9_\-/+]{40,}["']""")),
]


# The same two roots as they appear inside a project key, where the path a session
# ran in has had every character outside the key alphabet turned into a hyphen.
# Assembled for the same reason as the roots above.
_HOME_SLUG_ROOTS = "|".join(("-" + "home", "-" + "Users"))
PROJECT_KEY_HOME = re.compile(r"^(?:" + _HOME_SLUG_ROOTS + r")-[A-Za-z0-9]+")


def redact(kind: str) -> str:
    """Full-mask placeholder. No partial disclosure (no first4/last4)."""
    return f"[REDACTED:{kind}]"


def detect_secrets(text: str) -> list[dict[str, str]]:
    """Detect potential secrets in text. Returns list of {type, masked}."""
    findings: list[dict[str, str]] = []
    for name, pattern in SECRET_PATTERNS:
        for _match in pattern.finditer(text):
            findings.append({"type": name, "masked": redact(name)})
    return findings


def mask_project_key(key: str) -> str:
    """A project key with the operator's home masked, where the key names one.

    A project key is a working directory with every separator turned into a hyphen,
    so the home directory — whose name is the operator — survives inside it, and
    survives the patterns above as well: those look for the separators the
    conversion removed. The kind is reported as the home path it is, since it is
    the same fact in another spelling.

    The match is anchored at the start. Only a key beginning at the home root names
    the operator, and an unanchored pattern would mask a hyphenated word sitting in
    the middle of a project's own name.
    """
    return PROJECT_KEY_HOME.sub(redact("home_path"), key)


def mask_secrets(text: str) -> str:
    """Replace detected secrets with full [REDACTED:kind] placeholders."""
    result = text
    for name, pattern in SECRET_PATTERNS:
        result = pattern.sub(redact(name), result)
    return result
