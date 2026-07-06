# Provenance Guard

## Project Overview

Provenance Guard is a transparency-focused text analysis system. When a piece of writing is submitted, it runs two explainable heuristic signals over the text, combines them into a single confidence score, and returns a cautious transparency label describing whether the writing looks likely human-written, uncertain / possibly AI-assisted, or likely AI-generated or heavily AI-assisted.

**This is not an AI detector, and it does not prove authorship.** Both signals are simple, explainable writing-pattern heuristics (sentence-length consistency and concrete-detail density) that can and do produce false positives — a polished human essay can score as "likely AI," and an AI response with fabricated personal details can score as "likely human." Every label is worded as an estimate based on writing patterns, never as an accusation, and every result comes with an appeal path. The goal is transparency and a paper trail, not enforcement.

## Features

- **Text submission endpoint** (`POST /submit`) — accepts raw text and a creator id, runs the full detection pipeline, and returns a structured result.
- **Two detection signals** — sentence uniformity and specificity/genericness, each independently explainable.
- **Confidence scoring** — a single `0.0`–`1.0` score combining both signals via a fixed, equal-weighted formula.
- **Transparency label generation** — one of three fixed label variants, chosen from the confidence score, each including the caveat that the result is not proof.
- **Appeals workflow** (`POST /appeal`) — lets a creator dispute a result; moves the submission to `under_review` and records the appeal.
- **Structured audit logging** — every submission and every appeal is written as a JSON line to `audit_log.jsonl`, retrievable via `GET /log`.
- **Rate limiting** — `POST /submit` is capped via Flask-Limiter to blunt scripted abuse while staying out of the way of normal manual use.

## Architecture

### Submission flow

A user submits text through `POST /submit`. The request is validated, a `content_id` (UUID) is generated, and the text is run through both detection signals. The two signal scores are combined into a single confidence score, which is mapped to one of the three transparency label variants. The full result is written to the audit log and stored in memory (keyed by `content_id`) so it can later be looked up by an appeal, and the JSON response is returned to the user.

```text
User submits text
        |
        v
POST /submit
        |
        v
Input Validation
        |
        v
Create content_id
        |
        v
Signal 1: Sentence Uniformity
        |
        v
Signal 2: Specificity and Personal Detail
        |
        v
Confidence Scoring
        |
        v
Transparency Label
        |
        v
Audit Log
        |
        v
Response to user
```

### Appeal flow

If a creator disagrees with a result, they submit `content_id` and their reasoning through `POST /appeal`. The system looks up the original submission in memory, and if it exists and has not already been appealed, updates its status to `under_review`, stores the appeal reasoning alongside the original scores, and writes an `appeal_submitted` event to the audit log. No re-classification happens automatically — the appeal is recorded for a human to review later.

```text
Creator submits appeal
        |
        v
POST /appeal
        |
        v
Find content_id
        |
        v
Update status to under_review
        |
        v
Audit Log
        |
        v
Appeal confirmation
```

## Detection Signals

### Signal 1: Sentence Uniformity

**What it measures:** how consistent sentence lengths are across the submitted text. The text is split into sentences, word counts per sentence are computed, and the coefficient of variation (standard deviation relative to the mean) is calculated. Low variation maps to a high score; high variation maps to a low score.

**Why it may differ between AI and human writing:** AI-generated text often has smooth, balanced sentence structure — sentences tend to cluster around a similar length. Human writing more often mixes short punchy sentences with long, meandering ones, or includes fragments.

**Output format:**

```json
{
  "name": "sentence_uniformity",
  "score": 0.72,
  "explanation": "The text has highly consistent sentence lengths, which can be associated with AI-assisted writing."
}
```

If the text has fewer than 3 sentences, there isn't enough data to compute a reliable variation, so the function returns a neutral default of `0.50` with an explanation that reliability is low, rather than guessing.

**Blind spots:** polished academic writing, professional/formal writing, and careful writing by non-native English speakers can all be legitimately uniform without being AI-generated. Conversely, AI can be prompted to write in a deliberately uneven, casual register, defeating this signal entirely. This signal should never be used alone.

### Signal 2: Specificity and Personal Detail

**What it measures:** whether the text contains concrete, checkable detail — numbers, dates (month names), first-person pronouns (`I`, `me`, `my`, `we`, `our`, `us`), capitalized proper-noun-like words that aren't just sentence-starting capitalization, and example phrases like "for example" or "in my experience." The count of these markers is normalized by word count into a detail density, which is converted into a **genericness** score — note that a *higher* score means *more* generic (fewer concrete details), not more specific.

**Why it may differ between AI and human writing:** human writing often carries details from lived experience — a date, a place, a name, a number. Generic AI output can sound polished and confident while saying very little that's concretely checkable.

**Output format:**

```json
{
  "name": "specificity_and_personal_detail",
  "score": 0.61,
  "explanation": "The text contains limited concrete detail, which may make it more generic."
}
```

If the text has fewer than 6 words, it returns a neutral default of `0.50` with a low-reliability explanation.

**Blind spots:** AI can fabricate dates, names, and numbers if prompted to, which would lower this score even though no real personal experience is behind it. Conversely, legitimately human writing that's intentionally general (short answers, summaries, casual pronoun-heavy chat without named entities) can score as generic simply because it lacks *the specific kinds of markers this heuristic counts* — this is a real, observed limitation and is discussed further below.

## Confidence Scoring

The two signal scores are combined with a fixed, equal-weighted average — the exact formula from the project's planning spec, implemented unchanged in `calculate_ai_likelihood_score`:

```text
confidence =
    (sentence_uniformity_score * 0.50)
    +
    (specificity_genericness_score * 0.50)
```

The confidence score means: **the degree to which the submitted text matches the system's selected AI-like writing patterns.**

It does **not** mean: **the probability that the text was definitely written by AI.**

Threshold ranges (not a binary cutoff at 0.5 — the middle range is intentionally wide):

| Range | Label category |
|---|---|
| `0.00–0.39` | Likely human-written |
| `0.40–0.69` | Possibly AI-assisted / uncertain |
| `0.70–1.00` | Likely AI-generated or heavily AI-assisted |

Two real examples generated by calling the running app's `/submit` endpoint, chosen to show meaningfully different scores:

### Example 1: Higher-confidence AI-like case

Input:

```text
Technology plays an important role in improving efficiency in modern organizations. Technology helps businesses achieve better outcomes through better processes. Technology also supports collaboration across departments and teams.
```

Signal scores:

- Sentence uniformity: 0.73
- Specificity/genericness: 0.90
- Combined confidence: 0.81

Resulting label:

```text
Likely AI-generated or heavily AI-assisted
```

### Example 2: Lower-confidence human-like case

Input:

```text
Ugh. I cant believe it. On July 14, 2022, my sister Maria and I drove 342 miles from Austin to New Orleans just to eat beignets at Cafe Du Monde, and honestly it was worth every mile. We got there at 6am. The line was insane, like 40 people deep, but we waited anyway because Maria said it was a bucket list thing for her. I ordered three orders. Three! My cousin Diego joined us later that afternoon after flying in from Miami.
```

Signal scores:

- Sentence uniformity: 0.15
- Specificity/genericness: 0.51
- Combined confidence: 0.33

Resulting label:

```text
Likely human-written
```

## Transparency Label Variants

### High-confidence human label

```text
Likely human-written

Confidence score: {score}

This text does not strongly match the AI-like writing patterns checked by Provenance Guard. The writing shows enough variation, specificity, or personal detail that the system does not have strong reason to flag it as AI-generated.

This result is an estimate based on writing patterns, not proof of authorship.
```

### Uncertain label

```text
Possibly AI-assisted

Confidence score: {score}

This text shows some patterns that can be associated with AI-assisted writing, but the result is uncertain. The signal results are mixed, so this label should not be treated as evidence of misconduct.

This result is an estimate based on writing patterns, not proof of authorship. The creator may submit an appeal if they believe this label is incorrect.
```

### High-confidence AI label

```text
Likely AI-generated or heavily AI-assisted

Confidence score: {score}

This text strongly matches the AI-like writing patterns checked by Provenance Guard, such as highly uniform sentence structure or limited concrete detail. However, this result is still not definitive proof that AI was used.

This label should be reviewed carefully before any decision is made. The creator may submit an appeal if they believe this label is incorrect.
```

## API Endpoints

### POST /submit

Analyzes submitted text and returns a transparency label. Rate-limited to 10 requests per minute / 100 per day.

Example request:

```json
{
  "text": "The submitted text to analyze.",
  "creator_id": "test-user-1"
}
```

Example response:

```json
{
  "content_id": "5d9aae69-113f-4a9f-b1e7-77af7b8ee2fa",
  "creator_id": "test-user-1",
  "attribution": "uncertain",
  "confidence": 0.65,
  "label": "Possibly AI-assisted",
  "label_category": "uncertain",
  "label_text": "Possibly AI-assisted\n\nConfidence score: 0.65\n\nThis text shows some patterns that can be associated with AI-assisted writing, but the result is uncertain...",
  "signals": {
    "sentence_uniformity": {
      "name": "sentence_uniformity",
      "score": 0.43,
      "explanation": "The text has moderately consistent sentence lengths, which is a mixed signal."
    },
    "specificity_and_personal_detail": {
      "name": "specificity_and_personal_detail",
      "score": 0.87,
      "explanation": "The text contains limited concrete detail, which may make it more generic."
    }
  },
  "appeal_available": true,
  "status": "classified"
}
```

Validation errors (missing/empty `text` or `creator_id`) return `400` with `{"error": "..."}`.

### POST /appeal

Lets a creator dispute a result by `content_id`. Moves the submission's status to `under_review` and logs the appeal.

Example request:

```json
{
  "content_id": "27b9dcb0-c4fd-40f5-8dfb-2970190a1f27",
  "creator_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical."
}
```

Example response:

```json
{
  "content_id": "27b9dcb0-c4fd-40f5-8dfb-2970190a1f27",
  "status": "under_review",
  "message": "Your appeal has been received and marked for review."
}
```

Error responses:

- `400` if `content_id` or `creator_reasoning` is missing or empty.
- `404` — `{"error": "content_id not found."}` — if the `content_id` doesn't match any submission from the current server run.
- `409` — `{"error": "This content has already been appealed."}` — if that content was already appealed.

### GET /log

Returns the 10 most recent structured audit log entries, newest first. Entries are either `submission_classified` or `appeal_submitted` events.

Example response:

```json
{
  "entries": [
    {
      "event": "appeal_submitted",
      "content_id": "27b9dcb0-c4fd-40f5-8dfb-2970190a1f27",
      "creator_id": "test-user-3",
      "timestamp": "2026-07-05T04:46:42.603258+00:00",
      "status": "under_review",
      "appeal_filed": true,
      "appeal_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical.",
      "original_attribution": "likely_ai",
      "original_confidence": 0.7,
      "sentence_uniformity_score": 0.5,
      "specificity_genericness_score": 0.9
    },
    {
      "event": "submission_classified",
      "content_id": "92e87189-5a79-4cc4-8087-2e5c15e2aa48",
      "creator_id": "test-user-ai-example",
      "timestamp": "2026-07-05T04:45:56.915293+00:00",
      "attribution": "likely_ai",
      "confidence": 0.81,
      "label_category": "likely_ai",
      "label_title": "Likely AI-generated or heavily AI-assisted",
      "sentence_uniformity_score": 0.73,
      "specificity_genericness_score": 0.9,
      "status": "classified",
      "appeal_filed": false
    }
  ]
}
```

## Audit Log

Every successful `/submit` and `/appeal` call writes one JSON line to `audit_log.jsonl` (append-only, human-inspectable, no print statements). Logging every decision — including the individual signal scores, not just the final label — is what makes the system's decisions traceable and appealable rather than a black box.

A submission entry includes: `event`, `content_id`, `creator_id`, `timestamp`, `attribution`, `confidence`, `label_category`, `label_title`, `sentence_uniformity_score`, `specificity_genericness_score`, `status`, `appeal_filed`.

An appeal entry includes: `event`, `content_id`, `creator_id`, `timestamp`, `status`, `appeal_filed`, `appeal_reasoning`, `original_attribution`, `original_confidence`, `sentence_uniformity_score`, `specificity_genericness_score`.

Real example — submission entry:

```json
{
  "event": "submission_classified",
  "content_id": "27b9dcb0-c4fd-40f5-8dfb-2970190a1f27",
  "creator_id": "test-user-3",
  "timestamp": "2026-07-05T04:45:56.904024+00:00",
  "attribution": "likely_ai",
  "confidence": 0.7,
  "label_category": "likely_ai",
  "label_title": "Likely AI-generated or heavily AI-assisted",
  "sentence_uniformity_score": 0.5,
  "specificity_genericness_score": 0.9,
  "status": "classified",
  "appeal_filed": false
}
```

Real example — appeal entry for the same `content_id`, filed moments later:

```json
{
  "event": "appeal_submitted",
  "content_id": "27b9dcb0-c4fd-40f5-8dfb-2970190a1f27",
  "creator_id": "test-user-3",
  "timestamp": "2026-07-05T04:46:42.603258+00:00",
  "status": "under_review",
  "appeal_filed": true,
  "appeal_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical.",
  "original_attribution": "likely_ai",
  "original_confidence": 0.7,
  "sentence_uniformity_score": 0.5,
  "specificity_genericness_score": 0.9
}
```

The audit log currently stores full submitted text nowhere — it stores scores, labels, and status only, not a text preview or the raw text — which limits reviewer context but keeps the log lightweight. See Known Limitations / Future Improvements.

## Appeals Workflow

Any creator who receives a result can appeal it — the endpoint takes only `content_id` and `creator_reasoning`, with no ownership check tying the appeal to the original `creator_id`. The creator provides the `content_id` returned by `/submit` and a free-text explanation of why they believe the label is wrong.

When an appeal is received, the system looks up `content_id` in the in-memory `submissions` store. If found and not already appealed, it flips `status` to `under_review`, stores the `appeal_reasoning`, and writes an `appeal_submitted` audit log entry that carries forward the original attribution, confidence, and both signal scores — so a reviewer reading the log later has the full context without a separate lookup. If the `content_id` doesn't exist, it returns `404`; if it was already appealed, it returns `409` rather than silently overwriting the first appeal.

This project does **not** implement automated re-classification (an appeal never changes the score or label automatically) or a human reviewer dashboard/UI — appeals are recorded and queryable through `GET /log`, and reviewing them is a manual process for now.

## Rate Limiting

`POST /submit` is rate-limited using Flask-Limiter, configured with an in-memory store:

```python
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)
```

```python
@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    ...
```

**10 per minute; 100 per day.** This allows normal manual use by a writer submitting one piece of text at a time, while limiting rapid scripted abuse (e.g., someone hammering the endpoint to probe the scoring heuristics or flood the audit log). The limit is scoped to `/submit` only — `/appeal` and `/log` are not rate-limited, since they're not the endpoint that runs the (relatively cheap but non-zero) detection pipeline.

Test command:

```bash
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:5000/submit \
    -H "Content-Type: application/json" \
    -d '{"text": "This is a test submission for rate limit testing purposes only.", "creator_id": "ratelimit-test"}'
done
```

Actual output from a clean run (fresh server, no prior `/submit` calls in that minute):

```text
200
200
200
200
200
200
200
200
200
200
429
429
```

The first 10 requests succeed; the 11th and 12th are rejected. Note the limiter counts requests from the same client across the whole rolling minute — if you've already called `/submit` a few times manually before running this loop, you'll see fewer than 10 successes before the first 429, which is expected, not a bug.

## Setup and Running the Project

```bash
python -m venv .venv
source .venv/bin/activate          # Mac/Linux
source .venv/Scripts/activate      # Windows (Git Bash)
# or: .venv\Scripts\activate       # Windows (Command Prompt)
pip install -r requirements.txt
python app.py
```

The server starts on `http://localhost:5000` in debug mode. The audit log is created at `audit_log.jsonl` in the project root on the first successful submission.

### Test /submit

```bash
curl -s -X POST http://localhost:5000/submit \
  -H "Content-Type: application/json" \
  -d '{"text": "The sun dipped below the horizon, painting the sky in hues of amber and rose. I sat on the porch, coffee in hand, watching the neighborhood slowly go quiet.", "creator_id": "test-user-1"}' | python -m json.tool
```

### Test /appeal

```bash
curl -s -X POST http://localhost:5000/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "PASTE-CONTENT-ID-HERE", "creator_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical."}' | python -m json.tool
```

### Test /log

```bash
curl -s http://localhost:5000/log | python -m json.tool
```

## Testing Results

Four cases run against the live app (`POST /submit`), scores taken directly from the responses:

| Case | Description | Sentence uniformity | Genericness | Confidence | Attribution / label | Matched intuition? |
|---|---|---|---|---|---|---|
| 1 | Clearly AI-like ("Artificial intelligence represents a transformative paradigm shift...") | 0.43 | 0.87 | **0.65** | uncertain / Possibly AI-assisted | Partially — genericness correctly registered strongly, but sentence uniformity was only moderate because this passage's sentence lengths (10/22/11 words) actually vary quite a bit, keeping the combined score just under the `likely_ai` line. |
| 2 | Clearly human-like (casual ramen review, first-person, lowercase) | 0.15 | 0.78 | **0.47** | uncertain / Possibly AI-assisted | Partially — sentence uniformity correctly read as strongly human, but genericness scored higher than expected because the text has plenty of pronouns but no dates, numbers, or named entities, which this heuristic weighs more heavily. |
| 3 | Borderline formal human (monetary-policy paragraph, 2 sentences) | 0.50 (too few sentences for a reliable score) | 0.90 | **0.70** | likely_ai / Likely AI-generated or heavily AI-assisted | No — this is a real false positive. A human could plausibly have written this; the short, detail-free, formal passage pushed genericness to 0.90 and there wasn't enough sentence data to pull the score down. This was used to test the appeal flow (see Audit Log section). |
| 4 | Borderline lightly-edited AI (remote-work reflection, mixed personal/generic framing) | 0.49 | 0.87 | **0.68** | uncertain / Possibly AI-assisted | Yes — landed squarely in the intended wide uncertain band rather than committing to either extreme, which is the desired behavior for genuinely ambiguous text. |

## Known Limitations

- **Formal, detail-free human writing can be mislabeled as AI.** Case 3 above is a live example: a two-sentence academic-style paragraph about monetary policy scored `likely_ai` at confidence 0.70. Formal writing style with no personal anecdotes drives specificity/genericness toward 1.0, and short passages fall back to a neutral 0.50 sentence-uniformity default rather than a low one — there's nothing in the signals that distinguishes "genuinely uses no personal detail because it's an academic topic" from "genuinely AI-generated."
- **Casual, pronoun-heavy human writing can still read as generic.** Case 2 above: a first-person, opinionated restaurant review scored 0.78 on genericness despite being unmistakably personal, because the specificity signal weighs named entities, dates, and numbers more heavily than first-person pronoun density alone, and this text had pronouns but no proper nouns, dates, or numbers.
- **Poetry and other repetition-heavy creative writing would likely be misread by Signal 1.** Sentence uniformity treats consistent, short, repeated line lengths as a sign of machine-like structure — but that's a normal and intentional creative choice in poetry, song lyrics, or refrains. This wasn't tested live in this milestone, but follows directly from how the coefficient-of-variation calculation works.
- **AI text with fabricated personal details would defeat Signal 2.** Because the specificity heuristic only counts the *presence* of markers like dates, numbers, and pronouns — not whether they're true — an AI response instructed to include a fake name, date, and number would score as more human-like (lower genericness) despite containing no real lived experience.

## Spec Reflection

### How the spec helped

Writing `planning.md` before any code meant the signal output shape (`{"name", "score", "explanation"}`), the three exact confidence thresholds, and the three exact label variant texts were all locked in before Milestone 3 started. In practice this meant each milestone was purely additive — Milestone 4 added a second signal function without touching the first, and Milestone 5 added label generation and appeals without needing to change the `/submit` response contract that Milestone 3 established. There was no rework caused by an endpoint shape changing mid-project.

### Where implementation diverged from the spec

The biggest divergence is storage: submissions live in a plain in-memory Python dict (`submissions = {}`) rather than any persistent store. This means appeals only work against `content_id` values created during the current server process's lifetime — restarting the app clears all appealable submissions, even though the JSONL audit log itself is durable. A production version would need a real database so appeals survive restarts and work across multiple server instances. The specificity/genericness scoring formula's exact density-to-score mapping (dividing detail density by 0.55, then scaling) also wasn't fully specified in the original plan beyond "more detail = lower score" — it was tuned by hand against the plan's own two calibration examples during implementation, and it doesn't perfectly hit the planned 0.10–0.30 / 0.70–0.90 target ranges (it landed at 0.33 and 0.90 respectively) — close, but an example of a heuristic that would need real calibration against labeled data rather than hand-tuning against two examples.

## AI Usage

**Instance 1:** I used an AI coding assistant to generate the initial Flask app skeleton, the `POST /submit` endpoint, and the first detection signal (`calculate_sentence_uniformity`) in Milestone 3, working directly from my planning.md's exact output-format spec. It produced a working route, input validation, and a JSONL audit logger. I verified the signal function directly with three test inputs (uniform AI-like text, varied human-like text, and a too-short fragment) and confirmed the scores landed in the expected ranges before trusting it inside the endpoint.

**Instance 2:** I used the same assistant to draft `calculate_specificity_genericness` and the real confidence-scoring and label-mapping functions in Milestones 4 and 5. It proposed a marker-counting heuristic (numbers, month names, pronouns, proper-noun-like capitalization, example phrases) and a density-to-score formula. I checked the output against my planning.md's own calibration examples (the Django/FPT Software personal example and the generic "Technology plays an important role" example) and against the exact threshold table, and confirmed all three label variants were reachable by calling `generate_transparency_label(0.20)`, `(0.55)`, and `(0.82)` directly before wiring it into `/submit`.

**Instance 3:** I used the assistant to write the `/appeal` endpoint, the curl test commands, and the rate-limit test loop in Milestone 5. I ran the commands myself against the live server and confirmed the audit log showed both a `submission_classified` and an `appeal_submitted` entry for the same `content_id`, and that the 11th and 12th rapid `/submit` calls in one minute returned `429` while the first 10 returned `200`.

## Future Improvements

- Replace hand-tuned heuristic thresholds with values calibrated against a labeled dataset of known human and AI text.
- Add a real database for persistent submissions and appeals, so appeals survive a server restart.
- Add a human reviewer dashboard instead of relying on `GET /log` for appeal review.
- Add content-type awareness (essay, poem, email, reflection) so genre-specific false positives — like poetry's intentional repetition — can be flagged or weighted differently.
- Add an explicit reliability warning in the API response (not just the signal explanation) when text is too short for either signal to be trustworthy.
- Store less raw content in the audit trail (currently no raw text is stored at all, only scores and labels) and consider whether even a short text preview is worth the added privacy risk.
