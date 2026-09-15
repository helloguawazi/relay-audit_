"""Model identity normalisation and cross-provider matching.

Relays name the same model in mutually incompatible ways:

    claude-sonnet-5
    anthropic/claude-sonnet-5
    claude-sonnet-5-20250101
    Claude-Sonnet-5
    claude-sonnet-5-thinking
    aws/anthropic/claude-sonnet-5

Comparing prices requires mapping all of those onto one canonical id. Guessing
here would silently produce wrong comparisons, so the matcher only ever matches
on an explicit set of patterns declared in models.toml, and reports anything it
could not match instead of inventing a row.
"""

from __future__ import annotations

import re

# Suffixes that denote a routing or capability variant rather than a different
# model. They are recorded as a variant tag instead of being discarded, because
# a "thinking" variant legitimately costs more than the base model.
VARIANT_SUFFIXES = (
    "thinking",
    "reasoning",
    "high",
    "low",
    "medium",
    "max",
    "preview",
    "latest",
    "beta",
    "free",
    "extended",
)

# Vendor / routing prefixes that carry no pricing meaning.
VENDOR_PREFIXES = (
    "anthropic/",
    "openai/",
    "google/",
    "aws/",
    "azure/",
    "vertex/",
    "bedrock/",
    "gcp/",
    "~",
)


def normalise(model_id: str) -> tuple[str, str | None]:
    """Return (canonical_base, variant).

    Handles the three shapes relays actually use for the same model:

        'anthropic/claude-sonnet-5'          -> ('claude-sonnet-5', None)
        'Claude-Sonnet-5-20250101'           -> ('claude-sonnet-5', None)
        'Claude Opus 4.8'                    -> ('claude-opus-4-8', None)   # display name
        'claude-sonnet-5-thinking'           -> ('claude-sonnet-5', 'thinking')
        'GPT-5.6 Terra'                      -> ('gpt-5-6-terra', None)

    Spaces, dots and underscores are folded to hyphens, because relays commonly
    publish a human display name where a model id is expected. Version numbers
    are preserved: '4.8' becomes '4-8' and must not collapse into '4'.
    """
    s = (model_id or "").strip().lower()
    changed = True
    while changed:
        changed = False
        for p in VENDOR_PREFIXES:
            if s.startswith(p):
                s = s[len(p):]
                changed = True
    # Fold the separator variants that distinguish display names from ids.
    # A slash is included because an unknown vendor namespace ('deepseek/...')
    # survives the prefix stripping above and is a separator like any other.
    s = re.sub(r"[\s_./]+", "-", s)
    # Trailing date stamps: -20250101, -2025-01-01, :20250101
    s = re.sub(r"[-:@]20\d{2}[-]?\d{2}[-]?\d{2}$", "", s)
    s = re.sub(r"[-:@]\d{6,8}$", "", s)

    variant = None
    for v in VARIANT_SUFFIXES:
        if s.endswith("-" + v):
            variant = v
            s = s[: -(len(v) + 1)]
            break
    s = s.strip("-: ")
    s = re.sub(r"-{2,}", "-", s)
    return s, variant


def matches_pattern(model_id: str, pattern: str) -> bool:
    """Glob match against a normalised model id.

    `*` matches any run of characters. Both sides are normalised, so a pattern
    can be written the way a model id is normally written:

        'claude-opus-4-8'             matches 'Claude Opus 4.8'
        'claude-sonnet-*'             matches 'anthropic/claude-sonnet-5-thinking'
    """
    base, _ = normalise(model_id)
    pat, _ = normalise(pattern)
    if "*" not in pat:
        return base == pat
    # A normalised display name turns '4.8' into '4-8', but people write the
    # pattern as '4.8' or '48'. Allow the hyphen before a digit to be optional
    # so all three spellings match one pattern.
    regex = "^" + re.escape(pat).replace(r"\-", r"-?").replace(r"\*", ".*") + "$"
    return re.match(regex, base) is not None


def classify(model_id: str, specs: dict) -> str | None:
    """Return the key of the first model spec whose patterns match, else None.

    Specs declaring `match` patterns win. A spec may also declare an exact
    `aliases` list, which is checked first so that a precise entry cannot be
    shadowed by a broader wildcard.
    """
    base, _ = normalise(model_id)
    for key, spec in specs.items():
        for alias in spec.get("aliases", []):
            if normalise(alias)[0] == base:
                return key
    for key, spec in specs.items():
        for pattern in spec.get("match", []):
            if matches_pattern(model_id, pattern):
                return key
    return None


def canonical_display(spec_key: str, spec: dict) -> str:
    return spec.get("display") or spec_key
