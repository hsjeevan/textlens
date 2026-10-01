import json

import nltk
import pytest

from app import nlp_engine
from app.nlp_engine import analyze_text


def test_result_shape():
    result = analyze_text("Hello world. This is a test.")
    assert set(result) == {
        "word_count", "sentence_count", "top_keywords", "tone", "themes",
    }
    # Must be JSON-serialisable so it can be returned from FastAPI / cached in Redis.
    json.dumps(result)


def test_word_and_sentence_counts():
    result = analyze_text("The cat sat. The dog ran! Did the bird fly?")
    assert result["sentence_count"] == 3
    assert result["word_count"] == 10  # punctuation is not counted


def test_keywords_exclude_stopwords_and_are_ranked():
    text = (
        "Coverage is great. Coverage in the city is strong, "
        "and coverage downtown is the best. The signal is fine."
    )
    keywords = analyze_text(text)["top_keywords"]
    words = [k["word"] for k in keywords]
    assert words[0] == "coverage"
    assert keywords[0]["count"] == 3
    for stopword in ("the", "is", "and", "in"):
        assert stopword not in words


def test_top_keywords_capped_at_ten():
    text = " ".join(
        ["apple", "banana", "cherry", "grape", "lemon", "mango",
         "melon", "olive", "peach", "pear", "plum", "kiwi"]
    )
    assert len(analyze_text(text)["top_keywords"]) == 10


@pytest.mark.parametrize(
    "text, label",
    [
        ("I love this phone, the service is excellent and amazing!", "positive"),
        ("This is terrible. The worst support I have ever had, awful.", "negative"),
        ("The store opens at nine.", "neutral"),
    ],
)
def test_tone_label(text, label):
    assert analyze_text(text)["tone"]["label"] == label


def test_tone_indicators():
    ind = analyze_text("WHY is my bill so HIGH?! Seriously?")["tone"]["indicators"]
    assert ind["exclamation_count"] == 1
    assert ind["question_count"] == 2
    assert ind["uppercase_word_ratio"] > 0


def test_themes_detect_dominant():
    text = (
        "My bill had an extra charge and the fees keep rising. "
        "I want a refund on this payment. The signal is okay."
    )
    themes = analyze_text(text)["themes"]
    assert themes["dominant"] == ["billing_pricing"]
    assert themes["scores"]["billing_pricing"] > themes["scores"]["network_connectivity"]


def test_no_themes_when_nothing_matches():
    assert analyze_text("Purple elephants dance quietly.")["themes"] == {
        "scores": {}, "dominant": [],
    }


@pytest.mark.parametrize("text", ["", "   \n\t "])
def test_empty_input(text):
    result = analyze_text(text)
    assert result["word_count"] == 0
    assert result["sentence_count"] == 0
    assert result["top_keywords"] == []
    assert result["tone"]["label"] == "neutral"


def test_rejects_non_string():
    with pytest.raises(TypeError):
        analyze_text(None)


def test_ensure_nltk_resources_does_not_redownload(monkeypatch):
    downloads = []
    monkeypatch.setattr(nlp_engine, "_resources_ready", False)
    monkeypatch.setattr(nltk, "download", lambda pkg, **kw: downloads.append(pkg))
    nlp_engine.ensure_nltk_resources()
    assert downloads == []  # everything is already installed locally
