"""
Provenance Guard - Milestone 5 (production layer)

Adds on top of Milestone 4:
  - Full transparency label generation (generate_transparency_label)
  - POST /appeal endpoint with an in-memory submissions store
  - Rate limiting on POST /submit via Flask-Limiter
  - Structured audit log entries for both submission and appeal events

Automated re-classification, a reviewer UI, and authentication are NOT
part of this milestone and are intentionally left out.
"""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

LOG_PATH = Path(__file__).parent / "audit_log.jsonl"

# In-memory record of submissions created during the current server run.
# Appeals look content_id up here. This intentionally does not persist
# across restarts -- the JSONL audit log is the durable record.
submissions = {}

# Minimum number of sentences required before we trust the uniformity
# calculation. Below this, we return a default "not enough evidence" score.
MIN_SENTENCES_FOR_RELIABLE_SCORE = 3

# Minimum number of words required before we trust the specificity/
# genericness calculation. Below this, we return a default score.
MIN_WORDS_FOR_RELIABLE_SPECIFICITY = 6

# Concrete detail marker patterns used by Signal 2.
_NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%?\b")
_MONTH_PATTERN = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\b"
)
_FIRST_PERSON_PATTERN = re.compile(r"\b(I|me|my|mine|we|our|us)\b", re.IGNORECASE)
_EXAMPLE_PHRASE_PATTERN = re.compile(
    r"\b(for example|for instance|such as|in my experience|when i)\b",
    re.IGNORECASE,
)
_FIRST_PERSON_WORDS = {"i", "me", "my", "mine", "we", "our", "us"}


# ---------------------------------------------------------------------------
# Detection Signal 1: Sentence Uniformity
# ---------------------------------------------------------------------------

def _split_into_sentences(text):
    """Split text into sentences on ., !, or ?, dropping empty fragments."""
    raw_sentences = re.split(r"[.!?]+", text)
    return [s.strip() for s in raw_sentences if s.strip()]


def calculate_sentence_uniformity(text):
    """
    Measure how consistent sentence lengths are across the text.

    Lower variation in sentence length -> higher AI-likelihood score.
    Higher variation in sentence length -> lower AI-likelihood score.

    Returns a dict: {"name", "score", "explanation"}, score in [0.0, 1.0].
    """
    sentences = _split_into_sentences(text)

    if len(sentences) < MIN_SENTENCES_FOR_RELIABLE_SCORE:
        return {
            "name": "sentence_uniformity",
            "score": 0.50,
            "explanation": (
                "There is not enough sentence variety to analyze sentence "
                "uniformity reliably."
            ),
        }

    word_counts = [len(s.split()) for s in sentences]
    average_length = sum(word_counts) / len(word_counts)

    # Coefficient of variation: standard deviation relative to the mean.
    # This normalizes variation across texts with different average
    # sentence lengths, so a short-sentence text and a long-sentence text
    # with similarly "even" rhythm score similarly.
    variance = sum((count - average_length) ** 2 for count in word_counts) / len(word_counts)
    std_dev = variance ** 0.5
    coefficient_of_variation = std_dev / average_length if average_length > 0 else 0

    # Map coefficient of variation to a 0.0-1.0 AI-likelihood score.
    # Low variation (uniform) -> score near 0.9. High variation -> score near 0.1.
    # A coefficient of variation of ~0.6 or higher is treated as "highly varied".
    normalized_variation = min(coefficient_of_variation / 0.6, 1.0)
    score = 0.9 - (normalized_variation * 0.75)
    score = round(max(0.0, min(1.0, score)), 2)

    if score >= 0.70:
        explanation = (
            "The text has highly consistent sentence lengths, which can be "
            "associated with AI-assisted writing."
        )
    elif score >= 0.40:
        explanation = (
            "The text has moderately consistent sentence lengths, which is a "
            "mixed signal."
        )
    else:
        explanation = (
            "The text has widely varied sentence lengths, which is more "
            "consistent with human writing."
        )

    return {
        "name": "sentence_uniformity",
        "score": score,
        "explanation": explanation,
    }


# ---------------------------------------------------------------------------
# Detection Signal 2: Specificity and Personal Detail
# ---------------------------------------------------------------------------

def _count_proper_nouns(sentences):
    """
    Count capitalized words that are not the first word of their sentence
    (sentence-initial capitalization doesn't indicate a proper noun) and
    are not first-person pronouns (those are counted separately).
    """
    count = 0
    for sentence in sentences:
        words = sentence.split()
        for word in words[1:]:
            cleaned = word.strip(",.;:!?\"'()")
            if cleaned and cleaned[0].isupper() and cleaned.lower() not in _FIRST_PERSON_WORDS:
                count += 1
    return count


def calculate_specificity_genericness(text):
    """
    Measure whether the text contains concrete detail (names, dates,
    numbers, personal references) or reads as generic.

    NOTE: this score represents genericness, not specificity.
    Higher score = more generic = more AI-like.
    Lower score = more concrete detail = more human-like.

    Returns a dict: {"name", "score", "explanation"}, score in [0.0, 1.0].
    """
    words = text.split()

    if len(words) < MIN_WORDS_FOR_RELIABLE_SPECIFICITY:
        return {
            "name": "specificity_and_personal_detail",
            "score": 0.50,
            "explanation": (
                "There is not enough detail to analyze specificity reliably."
            ),
        }

    sentences = _split_into_sentences(text)

    marker_count = (
        len(_NUMBER_PATTERN.findall(text))
        + len(_MONTH_PATTERN.findall(text))
        + len(_FIRST_PERSON_PATTERN.findall(text))
        + len(_EXAMPLE_PHRASE_PATTERN.findall(text))
        + _count_proper_nouns(sentences)
    )

    detail_density = marker_count / len(words)

    # Higher detail density -> lower genericness score.
    # A density of ~0.55 or higher is treated as "very detailed".
    normalized_density = min(detail_density / 0.55, 1.0)
    score = 0.9 - (normalized_density * 0.75)
    score = round(max(0.0, min(1.0, score)), 2)

    if score >= 0.70:
        explanation = (
            "The text contains limited concrete detail, which may make it "
            "more generic."
        )
    elif score >= 0.40:
        explanation = (
            "The text contains a moderate amount of concrete detail, which "
            "is a mixed signal."
        )
    else:
        explanation = (
            "The text contains a good amount of concrete, personal detail, "
            "which is more consistent with human writing."
        )

    return {
        "name": "specificity_and_personal_detail",
        "score": score,
        "explanation": explanation,
    }


# ---------------------------------------------------------------------------
# Confidence scoring and label mapping
# ---------------------------------------------------------------------------

def calculate_ai_likelihood_score(sentence_uniformity_result, specificity_result):
    """
    Combine both signal scores into a single ai_likelihood_score using the
    exact weighted-average formula from planning.md. Both signals are
    weighted equally in this version.

    This score represents the degree to which the text matches the
    system's selected AI-like writing patterns -- it is NOT the probability
    that the text was definitely written by AI.
    """
    sentence_uniformity_score = sentence_uniformity_result["score"]
    specificity_genericness_score = specificity_result["score"]

    ai_likelihood_score = (
        (sentence_uniformity_score * 0.50) + (specificity_genericness_score * 0.50)
    )
    ai_likelihood_score = round(max(0.0, min(1.0, ai_likelihood_score)), 2)
    return ai_likelihood_score


# Full label text for each of the three variants from planning.md.
# label_text is assembled as: title + confidence score + this body.
_LABEL_VARIANTS = {
    "likely_human": {
        "label_title": "Likely human-written",
        "label_body": (
            "This text does not strongly match the AI-like writing patterns "
            "checked by Provenance Guard. The writing shows enough "
            "variation, specificity, or personal detail that the system "
            "does not have strong reason to flag it as AI-generated.\n\n"
            "This result is an estimate based on writing patterns, not "
            "proof of authorship."
        ),
    },
    "uncertain": {
        "label_title": "Possibly AI-assisted",
        "label_body": (
            "This text shows some patterns that can be associated with "
            "AI-assisted writing, but the result is uncertain. The signal "
            "results are mixed, so this label should not be treated as "
            "evidence of misconduct.\n\n"
            "This result is an estimate based on writing patterns, not "
            "proof of authorship. The creator may submit an appeal if they "
            "believe this label is incorrect."
        ),
    },
    "likely_ai": {
        "label_title": "Likely AI-generated or heavily AI-assisted",
        "label_body": (
            "This text strongly matches the AI-like writing patterns "
            "checked by Provenance Guard, such as highly uniform sentence "
            "structure or limited concrete detail. However, this result is "
            "still not definitive proof that AI was used.\n\n"
            "This label should be reviewed carefully before any decision "
            "is made. The creator may submit an appeal if they believe "
            "this label is incorrect."
        ),
    },
}


def generate_transparency_label(confidence_score):
    """
    Map a combined confidence score to one of the three exact transparency
    label variants from planning.md, using the exact thresholds.
    Intentionally not a binary cutoff at 0.5 -- the middle range is wide
    on purpose.

    Returns a dict: {"label_category", "label_title", "label_text"}.
    """
    if confidence_score >= 0.70:
        label_category = "likely_ai"
    elif confidence_score >= 0.40:
        label_category = "uncertain"
    else:
        label_category = "likely_human"

    variant = _LABEL_VARIANTS[label_category]
    label_text = (
        f"{variant['label_title']}\n\n"
        f"Confidence score: {confidence_score}\n\n"
        f"{variant['label_body']}"
    )

    return {
        "label_category": label_category,
        "label_title": variant["label_title"],
        "label_text": label_text,
    }


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def write_log_entry(entry):
    """Append one structured JSON log entry to the JSONL audit log."""
    with open(LOG_PATH, "a") as log_file:
        log_file.write(json.dumps(entry) + "\n")


def get_log(limit=10):
    """Return the most recent `limit` audit log entries, newest last read but
    returned newest-first."""
    if not LOG_PATH.exists():
        return []

    with open(LOG_PATH, "r") as log_file:
        lines = [line.strip() for line in log_file if line.strip()]

    recent_lines = lines[-limit:]
    entries = [json.loads(line) for line in recent_lines]
    entries.reverse()  # newest first
    return entries


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def validate_submission(payload):
    """Return an error message string if invalid, otherwise None."""
    if not isinstance(payload, dict):
        return "Request body must be a JSON object."

    text = payload.get("text")
    creator_id = payload.get("creator_id")

    if text is None:
        return "text is required."
    if not isinstance(text, str) or not text.strip():
        return "text must be a non-empty string."

    if creator_id is None:
        return "creator_id is required."
    if not isinstance(creator_id, str) or not creator_id.strip():
        return "creator_id must be a non-empty string."

    return None


def validate_appeal(payload):
    """Return an error message string if invalid, otherwise None."""
    if not isinstance(payload, dict):
        return "Request body must be a JSON object."

    content_id = payload.get("content_id")
    creator_reasoning = payload.get("creator_reasoning")

    if content_id is None:
        return "content_id is required."
    if not isinstance(content_id, str) or not content_id.strip():
        return "content_id must be a non-empty string."

    if creator_reasoning is None:
        return "creator_reasoning is required."
    if not isinstance(creator_reasoning, str) or not creator_reasoning.strip():
        return "creator_reasoning must be a non-empty string."

    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    payload = request.get_json(silent=True)

    error = validate_submission(payload)
    if error:
        return jsonify({"error": error}), 400

    text = payload["text"]
    creator_id = payload["creator_id"]

    content_id = str(uuid.uuid4())

    signal_1_result = calculate_sentence_uniformity(text)
    signal_2_result = calculate_specificity_genericness(text)

    confidence = calculate_ai_likelihood_score(signal_1_result, signal_2_result)
    label = generate_transparency_label(confidence)
    attribution = label["label_category"]

    submissions[content_id] = {
        "content_id": content_id,
        "creator_id": creator_id,
        "attribution": attribution,
        "confidence": confidence,
        "label_category": label["label_category"],
        "label_title": label["label_title"],
        "sentence_uniformity_score": signal_1_result["score"],
        "specificity_genericness_score": signal_2_result["score"],
        "status": "classified",
        "appeal_filed": False,
    }

    log_entry = {
        "event": "submission_classified",
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attribution": attribution,
        "confidence": confidence,
        "label_category": label["label_category"],
        "label_title": label["label_title"],
        "sentence_uniformity_score": signal_1_result["score"],
        "specificity_genericness_score": signal_2_result["score"],
        "status": "classified",
        "appeal_filed": False,
    }
    write_log_entry(log_entry)

    response = {
        "content_id": content_id,
        "creator_id": creator_id,
        "attribution": attribution,
        "confidence": confidence,
        "label": label["label_title"],
        "label_category": label["label_category"],
        "label_text": label["label_text"],
        "signals": {
            "sentence_uniformity": signal_1_result,
            "specificity_and_personal_detail": signal_2_result,
        },
        "appeal_available": True,
        "status": "classified",
    }
    return jsonify(response), 200


@app.route("/appeal", methods=["POST"])
def appeal():
    payload = request.get_json(silent=True)

    error = validate_appeal(payload)
    if error:
        return jsonify({"error": error}), 400

    content_id = payload["content_id"]
    creator_reasoning = payload["creator_reasoning"]

    submission = submissions.get(content_id)
    if submission is None:
        return jsonify({"error": "content_id not found."}), 404

    if submission["appeal_filed"]:
        return jsonify({"error": "This content has already been appealed."}), 409

    submission["status"] = "under_review"
    submission["appeal_filed"] = True
    submission["appeal_reasoning"] = creator_reasoning

    log_entry = {
        "event": "appeal_submitted",
        "content_id": content_id,
        "creator_id": submission["creator_id"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "under_review",
        "appeal_filed": True,
        "appeal_reasoning": creator_reasoning,
        "original_attribution": submission["attribution"],
        "original_confidence": submission["confidence"],
        "sentence_uniformity_score": submission["sentence_uniformity_score"],
        "specificity_genericness_score": submission["specificity_genericness_score"],
    }
    write_log_entry(log_entry)

    response = {
        "content_id": content_id,
        "status": "under_review",
        "message": "Your appeal has been received and marked for review.",
    }
    return jsonify(response), 200


@app.route("/log", methods=["GET"])
def log():
    entries = get_log(limit=10)
    return jsonify({"entries": entries}), 200


if __name__ == "__main__":
    app.run(debug=True, port=5000)
