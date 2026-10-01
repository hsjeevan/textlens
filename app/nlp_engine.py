"""Core NLP analysis for raw text.

`analyze_text` is the single entry point: it takes a raw string and returns a
JSON-serialisable dict with counts, top keywords, tone and theme indicators.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import nltk
from nltk.corpus import stopwords
from nltk.probability import FreqDist
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import sent_tokenize, word_tokenize

# package name for nltk.download -> paths nltk.data.find may locate it at.
# Some packages (wordnet, vader_lexicon) are only ever stored zipped, and
# find() does not match "corpora/wordnet" against "corpora/wordnet.zip".
_NLTK_RESOURCES = {
    "punkt_tab": ("tokenizers/punkt_tab", "tokenizers/punkt_tab.zip"),
    "stopwords": ("corpora/stopwords", "corpora/stopwords.zip"),
    "wordnet": ("corpora/wordnet", "corpora/wordnet.zip"),
    "vader_lexicon": ("sentiment/vader_lexicon", "sentiment/vader_lexicon.zip"),
}

# Lemmatised trigger words per theme. Deliberately small and easy to extend.
THEME_LEXICON: dict[str, set[str]] = {
    "customer_experience": {
        "customer", "service", "support", "help", "agent", "experience",
        "wait", "call", "chat", "representative", "satisfied", "frustrated",
    },
    "billing_pricing": {
        "bill", "billing", "charge", "price", "cost", "fee", "payment",
        "refund", "plan", "discount", "expensive", "cheap", "pay",
    },
    "network_connectivity": {
        "network", "signal", "coverage", "connection", "outage", "speed",
        "5g", "4g", "lte", "data", "wifi", "drop", "slow", "internet",
    },
    "technology_product": {
        "phone", "device", "app", "software", "update", "feature", "battery",
        "screen", "upgrade", "technology", "bug", "crash",
    },
    "business_finance": {
        "revenue", "profit", "market", "growth", "investor", "sale",
        "quarter", "strategy", "company", "earnings", "stock",
    },
}

POSITIVE_THRESHOLD = 0.05
NEGATIVE_THRESHOLD = -0.05
TOP_KEYWORDS = 10

_resources_ready = False


def _nltk_has(path: str) -> bool:
    try:
        nltk.data.find(path)
        return True
    except LookupError:
        return False


def ensure_nltk_resources(quiet: bool = True) -> None:
    """Download any missing NLTK corpora/models. Safe to call repeatedly."""
    global _resources_ready
    if _resources_ready:
        return
    for package, paths in _NLTK_RESOURCES.items():
        if not any(_nltk_has(path) for path in paths):
            nltk.download(package, quiet=quiet)
    _resources_ready = True


def tokenize(text: str) -> dict[str, list[str]]:
    """Split text into sentences and word tokens (punctuation-only tokens dropped).

    Returns plain lists so the result is JSON-serialisable and cacheable.
    """
    if not isinstance(text, str):
        raise TypeError(f"text must be str, got {type(text).__name__}")
    if not text.strip():
        return {"sentences": [], "words": []}

    ensure_nltk_resources()
    # A "word" is any token containing a letter or digit.
    words = [t for t in word_tokenize(text) if re.search(r"\w", t)]
    return {"sentences": sent_tokenize(text), "words": words}


def count_stats(tokens: dict[str, list[str]]) -> dict[str, int]:
    return {
        "word_count": len(tokens["words"]),
        "sentence_count": len(tokens["sentences"]),
    }


def extract_keywords(words: list[str], top_n: int = TOP_KEYWORDS) -> list[dict[str, Any]]:
    """Top `top_n` words by frequency, ignoring stopwords and very short words."""
    if not words:
        return []
    ensure_nltk_resources()
    stop = set(stopwords.words("english"))
    content = [
        w.lower()
        for w in words
        if w.isalpha() and len(w) > 2 and w.lower() not in stop
    ]
    freq = FreqDist(content)
    return [{"word": w, "count": c} for w, c in freq.most_common(top_n)]


def analyze_tone(text: str, words: list[str]) -> dict[str, Any]:
    """VADER sentiment label/scores plus punctuation and caps indicators."""
    if text.strip():
        ensure_nltk_resources()
        scores = SentimentIntensityAnalyzer().polarity_scores(text)
    else:
        scores = {"neg": 0.0, "neu": 0.0, "pos": 0.0, "compound": 0.0}

    compound = scores["compound"]
    if compound >= POSITIVE_THRESHOLD:
        label = "positive"
    elif compound <= NEGATIVE_THRESHOLD:
        label = "negative"
    else:
        label = "neutral"

    # "Shouting" words: all caps and longer than 1 char (ignores "I", "A").
    upper = sum(1 for w in words if len(w) > 1 and w.isupper())
    return {
        "label": label,
        "scores": scores,
        "indicators": {
            "exclamation_count": text.count("!"),
            "question_count": text.count("?"),
            "uppercase_word_ratio": round(upper / len(words), 4) if words else 0.0,
        },
    }


def detect_themes(words: list[str]) -> dict[str, Any]:
    """Count lemmatised theme trigger words and report the dominant theme(s)."""
    if not words:
        return {"scores": {}, "dominant": []}
    ensure_nltk_resources()
    lemmatizer = WordNetLemmatizer()
    counts = Counter(lemmatizer.lemmatize(w.lower()) for w in words)
    scores = {
        theme: sum(counts[t] for t in triggers)
        for theme, triggers in THEME_LEXICON.items()
    }
    scores = {theme: n for theme, n in scores.items() if n > 0}
    if not scores:
        return {"scores": {}, "dominant": []}
    best = max(scores.values())
    dominant = sorted(theme for theme, n in scores.items() if n == best)
    return {"scores": scores, "dominant": dominant}


def analyze_text(text: str, top_n: int = TOP_KEYWORDS) -> dict[str, Any]:
    """Analyse raw text and return summary statistics.

    Returns a dict with keys:
      word_count      -- number of word tokens (punctuation excluded)
      sentence_count  -- number of sentences
      top_keywords    -- up to `top_n` [{"word", "count"}] by frequency, stopwords removed
      tone            -- VADER sentiment label/scores plus punctuation/caps indicators
      themes          -- per-theme trigger-word counts and the dominant theme(s)

    Each key is produced by a standalone step function (`tokenize`, `count_stats`,
    `extract_keywords`, `analyze_tone`, `detect_themes`) so pipelines such as the
    Prefect flow can run and cache them individually.
    """
    tokens = tokenize(text)
    words = tokens["words"]
    return {
        **count_stats(tokens),
        "top_keywords": extract_keywords(words, top_n),
        "tone": analyze_tone(text, words),
        "themes": detect_themes(words),
    }
