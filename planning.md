# Provenance Guard — planning.md

## Project Overview

Provenance Guard is a transparency-focused text analysis system that estimates whether a submitted piece of writing appears likely human-written, uncertain/possibly AI-assisted, or likely AI-generated. The system does not prove authorship. Instead, it uses multiple explainable detection signals, combines them into a confidence score, shows a cautious transparency label, records the result in an audit log, and allows creators to appeal the result. The main goal is to support transparency while reducing harm from false positives.

Because AI detection can be unreliable, Provenance Guard should never say that a text was "definitely" written by AI. Every label should be presented as an estimate based on writing patterns, not as proof of misconduct.

---

## Architecture

### Architecture Narrative

When a user submits text, the system receives the raw text through `POST /submit`. The system validates the input, creates a unique submission ID, runs two detection signals, combines the signal outputs into a single AI-likelihood confidence score, maps that score to a transparency label, writes the result to the audit log, and returns the label, score, explanation, signal breakdown, and appeal option to the user. If a creator disagrees with the result, they can submit an appeal through `POST /appeal`. The system finds the original submission, updates the appeal status, stores the appeal reason, writes an appeal event to the audit log, and returns confirmation that the appeal was received.

### Submission Flow Diagram

```text
User submits text
      |
      | raw text
      v
  POST /submit
      |
      | text, optional creator_id
      v
  Input Validation
      |
      | valid text
      v
  Create Submission ID
      |
      | submission_id + raw text
      v
  Signal 1: Sentence Uniformity
      |
      | sentence_uniformity_score, explanation
      v
  Signal 2: Specificity and Personal Detail
      |
      | specificity_genericness_score, explanation
      v
  Confidence Scoring
      |
      | combined_ai_likelihood_score
      v
  Transparency Label Generator
      |
      | label_category, label_title, label_text
      v
  Audit Logger
      |
      | saved submission event
      v
  API Response
      |
      | submission_id, label, confidence_score, signal_breakdown, appeal option
      v
  User sees transparency label
```

### Appeal Flow Diagram

```text
Creator submits appeal
      |
      | submission_id + appeal_reason + optional supporting_context
      v
  POST /appeal
      |
      | appeal request
      v
  Find Existing Submission
      |
      | matching submission record
      v
  Update Appeal Status
      |
      | status changes from not_appealed to appealed
      v
  Audit Logger
      |
      | saved appeal event
      v
  API Response
      |
      | appeal confirmation
      v
  Creator sees appeal recorded message
```

---

## Core System Components

### 1. User Interface

The user interface allows a creator or reviewer to submit text and view the system's transparency label. It should display the confidence score, signal explanations, appeal status, and appeal option.

### 2. Submission API

The submission API receives submitted text, validates it, creates a submission ID, runs the detection pipeline, logs the result, and returns the final response.

### 3. Input Validator

The input validator checks whether the submitted text is usable. It should reject empty submissions and text that is too short to analyze fairly.

### 4. Detection Signal 1: Sentence Uniformity

This component measures whether the text has unusually consistent sentence lengths or sentence structure.

### 5. Detection Signal 2: Specificity and Personal Detail

This component measures whether the text contains concrete details, personal context, examples, names, numbers, dates, or specific references.

### 6. Confidence Scoring

This component combines the two detection signal scores into one AI-likelihood confidence score.

### 7. Transparency Label Generator

This component converts the confidence score into a readable label and explanation for the user.

### 8. Audit Logger

This component records each submission and appeal event so the system's decisions can be reviewed later.

### 9. Appeal API

This endpoint allows a creator to challenge a label. It updates the appeal status and stores the appeal reason.

---

## Detection Signals

The system will use two explainable heuristic signals. Each signal outputs a score from `0.0` to `1.0`. A score closer to `1.0` means the signal sees a stronger AI-like pattern. A score closer to `0.0` means the signal sees a stronger human-like pattern.

The two signals are:

1. Sentence Uniformity
2. Specificity and Personal Detail

---

## Signal 1: Sentence Uniformity

### What it measures

Sentence uniformity measures how consistent the sentence lengths are across the submitted text. It checks whether the text has a very even rhythm or whether sentence length varies naturally. AI-generated text often has smooth, balanced sentence structure. Human writing often has more unevenness, such as short sentences mixed with longer explanations, fragments, or less predictable structure.

### Output format

The function should return a dictionary like this:

```json
{
  "name": "sentence_uniformity",
  "score": 0.72,
  "explanation": "The text has highly consistent sentence lengths, which can be associated with AI-assisted writing."
}
```

The `score` must always be between `0.0` and `1.0`.

### Planned scoring method

1. Split the text into sentences.
2. Count the number of words in each sentence.
3. Calculate the average sentence length.
4. Calculate the variation in sentence length.
5. Convert the variation into a score.

General rule:

```text
Low sentence length variation = higher AI-likelihood score
High sentence length variation = lower AI-likelihood score
```

Example of uniform sentence lengths:

```text
Sentence lengths: [18, 20, 19, 21, 18]
Variation is low.
sentence_uniformity_score = high, around 0.75-0.90
```

Example of varied sentence lengths:

```text
Sentence lengths: [4, 28, 9, 41, 13]
Variation is high.
sentence_uniformity_score = low, around 0.15-0.35
```

### What it captures

This signal can capture writing that feels unusually polished, even, repetitive, or machine-like in rhythm.

### Blind spots

This signal can misclassify strong human writers who write in a polished academic or professional style. It may also misclassify non-native English speakers who use careful, structured writing. On the other hand, AI-generated text can be prompted to sound casual or uneven, which may reduce this signal's usefulness. Because of these blind spots, sentence uniformity should not be used alone.

---

## Signal 2: Specificity and Personal Detail

### What it measures

Specificity and personal detail measures whether the text includes concrete information. This includes names, dates, numbers, locations, first-person details, specific events, personal examples, or unique context. Human writing often includes details from actual experience. AI-generated writing can sometimes sound broad, generic, and polished without giving many concrete examples.

### Output format

The function should return a dictionary like this:

```json
{
  "name": "specificity_and_personal_detail",
  "score": 0.61,
  "explanation": "The text contains limited concrete detail, which may make it more generic."
}
```

Important: this score represents **genericness**, not specificity. A higher score means the text is more generic and therefore more AI-like. A lower score means the text contains more concrete details and therefore appears more human-like.

### Planned scoring method

1. Count concrete detail markers:
   - Numbers
   - Dates
   - Proper nouns or capitalized names
   - First-person words such as `I`, `me`, `my`, `we`, `our`
   - Specific time or place words
   - Example phrases such as `for example`, `when I`, `in my experience`
2. Normalize the count based on text length.
3. Convert the detail density into a genericness score.

General rule:

```text
More concrete details = lower genericness score
Fewer concrete details = higher genericness score
```

Example of specific personal writing:

```text
In June 2024, I worked on a Django project at FPT Software and improved dashboard loading time by 25%.
```

This has a company name, date, technology, metric, and personal context.

Expected score:

```text
specificity_genericness_score = low, around 0.10-0.30
```

Example of generic writing:

```text
Technology plays an important role in improving efficiency and helping organizations achieve better results.
```

Expected score:

```text
specificity_genericness_score = high, around 0.70-0.90
```

### What it captures

This signal can capture text that sounds polished but vague. It helps identify writing that lacks concrete detail or original context.

### Blind spots

Some human writing is intentionally general, especially summaries, school essays, policy explanations, introductions, or short responses. AI-generated writing can also include fake names, dates, and details if prompted. Therefore, this signal should not be treated as proof of authorship.

---

## Combining Signal Scores

The system will combine both signal scores into one `ai_likelihood_score`. Both signals will be weighted equally in the first version.

```text
ai_likelihood_score = (sentence_uniformity_score * 0.50) + (specificity_genericness_score * 0.50)
```

The result must be a decimal between `0.0` and `1.0`.

Example:

```json
{
  "sentence_uniformity_score": 0.72,
  "specificity_genericness_score": 0.61,
  "ai_likelihood_score": 0.665
}
```

Rounded result:

```text
confidence_score = 0.67
```

In this system, the confidence score means:

```text
The degree to which the submitted text matches the system's selected AI-like writing patterns.
```

It does **not** mean:

```text
The probability that the text was definitely written by AI.
```

---

## Uncertainty Representation

### What a confidence score means

The confidence score is an `AI-likelihood confidence score` from `0.0` to `1.0`.

- `0.0` means the text shows very few AI-like patterns according to the selected signals.
- `0.5` means the system is uncertain or mixed.
- `1.0` means the text strongly matches the selected AI-like patterns.

A score of `0.60` means:

```text
The text shows some patterns associated with AI-assisted writing, but the evidence is not strong enough to label it as likely AI-generated.
```

A score of `0.60` should produce an uncertain label, not a strong accusation.

### Score Calibration

The raw signal outputs will be mapped directly into the combined score using the weighted average formula. The system will not treat any single signal as decisive. A high score from one signal can be balanced by a lower score from another signal.

Example:

```text
sentence_uniformity_score = 0.85
specificity_genericness_score = 0.25
combined_score = 0.55
```

This should be uncertain because the text has uniform sentence structure but also includes specific personal detail.

### Thresholds

The system will use three score ranges.

| Score Range | Label Category | Meaning |
|---|---|---|
| `0.00-0.39` | High-confidence human | Text does not strongly match AI-like patterns. |
| `0.40-0.69` | Uncertain / possibly AI-assisted | Text shows mixed signals or moderate AI-like patterns. |
| `0.70-1.00` | High-confidence AI | Text strongly matches AI-like patterns. |

The system intentionally uses a wide uncertain range from `0.40` to `0.69` because AI detection is unreliable and false positives can be harmful.

---

## Transparency Label Design

The UI will show one of three label variants. Each label should include:

1. A short label title.
2. A confidence score.
3. A plain-English explanation.
4. A reminder that the result is not proof.
5. An appeal option when appropriate.

---

### Label Variant 1: High-Confidence Human

Score range:

```text
0.00-0.39
```

Exact label text:

```text
Likely human-written

Confidence score: {score}

This text does not strongly match the AI-like writing patterns checked by Provenance Guard. The writing shows enough variation, specificity, or personal detail that the system does not have strong reason to flag it as AI-generated.

This result is an estimate based on writing patterns, not proof of authorship.
```

---

### Label Variant 2: Uncertain / Possibly AI-Assisted

Score range:

```text
0.40-0.69
```

Exact label text:

```text
Possibly AI-assisted

Confidence score: {score}

This text shows some patterns that can be associated with AI-assisted writing, but the result is uncertain. The signal results are mixed, so this label should not be treated as evidence of misconduct.

This result is an estimate based on writing patterns, not proof of authorship. The creator may submit an appeal if they believe this label is incorrect.
```

---

### Label Variant 3: High-Confidence AI

Score range:

```text
0.70-1.00
```

Exact label text:

```text
Likely AI-generated or heavily AI-assisted

Confidence score: {score}

This text strongly matches the AI-like writing patterns checked by Provenance Guard, such as highly uniform sentence structure or limited concrete detail. However, this result is still not definitive proof that AI was used.

This label should be reviewed carefully before any decision is made. The creator may submit an appeal if they believe this label is incorrect.
```

---

## False Positive Scenario

A student submits a polished essay that they wrote themselves. The essay has consistent sentence lengths, formal transitions, and limited personal detail because the assignment required an academic tone. The sentence uniformity score is high, and the specificity genericness score is also high because the essay does not include many personal examples. As a result, the system may label the text as `Likely AI-generated or heavily AI-assisted`.

This is a false positive because the student actually wrote the essay. The system should handle this carefully. First, the confidence score should show uncertainty instead of presenting the result as proof. Second, the label should use cautious wording. Instead of accusing the student, the system should say that the text contains patterns sometimes associated with AI-assisted writing. Third, the result page should include an appeal option. The student can submit an appeal through `POST /appeal`, explaining that the essay was written independently and that the polished style came from revision or academic expectations. The appeal endpoint updates the submission status to `appealed`, records the appeal reason, and writes the event to the audit log.

This design helps reduce harm because the system does not automatically punish the creator. It provides transparency, uncertainty, and a process for correction.

---

## Appeals Workflow

### Who can submit an appeal?

The creator of the submitted text can submit an appeal. A reviewer or admin may also submit an appeal on behalf of the creator if the creator provides an explanation.

### When can an appeal be submitted?

An appeal can be submitted for any result, but it is most important for:

- `Possibly AI-assisted`
- `Likely AI-generated or heavily AI-assisted`

### What information does the creator provide?

The appeal request should include:

```json
{
  "submission_id": "abc123",
  "creator_id": "optional_creator_id",
  "appeal_reason": "I wrote this myself and revised it several times.",
  "supporting_context": "Optional explanation, draft history, assignment context, or notes."
}
```

The `appeal_reason` is required. The `supporting_context` is optional.

### What happens when an appeal is received?

When the system receives an appeal:

1. It checks whether the `submission_id` exists.
2. It checks whether the submission has already been appealed.
3. It updates the submission status from `not_appealed` to `appealed`.
4. It stores the appeal reason and optional supporting context.
5. It writes an appeal event to the audit log.
6. It returns a confirmation response.

### Appeal status values

The system may use these statuses:

| Status | Meaning |
|---|---|
| `not_appealed` | No appeal has been submitted. |
| `appealed` | The creator has submitted an appeal. |
| `under_review` | A human reviewer is reviewing the appeal. |
| `resolved_label_upheld` | Reviewer kept the original label. |
| `resolved_label_changed` | Reviewer changed the original label. |

For the first implementation, the system only needs to support:

```text
not_appealed
appealed
```

The other statuses can be used as stretch features.

### Appeal API

Endpoint:

```text
POST /appeal
```

Request:

```json
{
  "submission_id": "abc123",
  "appeal_reason": "I wrote this myself. The style is formal because this was an academic assignment.",
  "supporting_context": "I can provide outlines and earlier drafts if needed."
}
```

Response:

```json
{
  "submission_id": "abc123",
  "appeal_status": "appealed",
  "message": "Your appeal has been recorded. A reviewer can now examine the original result, signal scores, and your explanation."
}
```

### What gets logged?

When an appeal is submitted, the audit log should record:

```json
{
  "event": "appeal_submitted",
  "submission_id": "abc123",
  "timestamp": "2026-07-04T10:45:00",
  "previous_appeal_status": "not_appealed",
  "new_appeal_status": "appealed",
  "appeal_reason": "I wrote this myself. The style is formal because this was an academic assignment.",
  "supporting_context": "I can provide outlines and earlier drafts if needed."
}
```

### What would a human reviewer see?

A human reviewer opening the appeal queue should see:

```json
{
  "submission_id": "abc123",
  "original_text_preview": "First 200 characters of the submitted text...",
  "original_label": "Possibly AI-assisted",
  "confidence_score": 0.62,
  "signal_breakdown": {
    "sentence_uniformity": 0.75,
    "specificity_and_personal_detail": 0.49
  },
  "original_explanation": "The text had consistent sentence structure but some concrete detail.",
  "appeal_reason": "I wrote this myself and revised it several times.",
  "supporting_context": "The assignment required a formal tone.",
  "appeal_status": "appealed",
  "created_at": "2026-07-04T10:30:00",
  "appealed_at": "2026-07-04T10:45:00"
}
```

The reviewer should not only see the final label. They should see the signal scores and explanation so they can understand why the system produced that result.

---

## API Surface

### POST /submit

Purpose: Analyze submitted text and return a transparency label.

Request body:

```json
{
  "text": "The submitted text to analyze.",
  "creator_id": "optional_creator_id"
}
```

Success response:

```json
{
  "submission_id": "abc123",
  "label_category": "uncertain",
  "label_title": "Possibly AI-assisted",
  "confidence_score": 0.67,
  "signals": {
    "sentence_uniformity": {
      "score": 0.72,
      "explanation": "The text has highly consistent sentence lengths."
    },
    "specificity_and_personal_detail": {
      "score": 0.61,
      "explanation": "The text contains limited concrete detail."
    }
  },
  "label_text": "Possibly AI-assisted\n\nConfidence score: 0.67\n\nThis text shows some patterns that can be associated with AI-assisted writing, but the result is uncertain...",
  "appeal_available": true,
  "appeal_status": "not_appealed"
}
```

Error response:

```json
{
  "error": "Text is too short to analyze fairly. Please submit a longer sample."
}
```

---

### POST /appeal

Purpose: Allow a creator to appeal a label.

Request body:

```json
{
  "submission_id": "abc123",
  "appeal_reason": "I wrote this myself and revised it several times.",
  "supporting_context": "The assignment required a formal tone."
}
```

Success response:

```json
{
  "submission_id": "abc123",
  "appeal_status": "appealed",
  "message": "Your appeal has been recorded."
}
```

Error response: submission not found

```json
{
  "error": "Submission ID not found."
}
```

Error response: already appealed

```json
{
  "error": "This submission has already been appealed."
}
```

---

### GET /submission/{submission_id}

Purpose: Return stored result for a previous submission.

Response body:

```json
{
  "submission_id": "abc123",
  "label_title": "Possibly AI-assisted",
  "confidence_score": 0.67,
  "signals": {
    "sentence_uniformity": 0.72,
    "specificity_and_personal_detail": 0.61
  },
  "appeal_status": "not_appealed"
}
```

---

### GET /appeals

Purpose: Return appealed submissions for human review.

Response body:

```json
{
  "appeals": [
    {
      "submission_id": "abc123",
      "original_label": "Possibly AI-assisted",
      "confidence_score": 0.67,
      "appeal_reason": "I wrote this myself and revised it several times.",
      "appeal_status": "appealed"
    }
  ]
}
```

---

## Audit Logging Plan

The audit log should make system decisions traceable.

### Submission log entry

```json
{
  "event": "submission_created",
  "submission_id": "abc123",
  "timestamp": "2026-07-04T10:30:00",
  "text_preview": "First 200 characters of submitted text...",
  "sentence_uniformity_score": 0.72,
  "specificity_genericness_score": 0.61,
  "combined_confidence_score": 0.67,
  "label_category": "uncertain",
  "label_title": "Possibly AI-assisted",
  "appeal_status": "not_appealed"
}
```

### Appeal log entry

```json
{
  "event": "appeal_submitted",
  "submission_id": "abc123",
  "timestamp": "2026-07-04T10:45:00",
  "previous_appeal_status": "not_appealed",
  "new_appeal_status": "appealed",
  "appeal_reason": "I wrote this myself and revised it several times.",
  "supporting_context": "The assignment required a formal tone."
}
```

### Privacy note

The audit log should store a text preview instead of the full submitted text when possible. This reduces privacy risk while still allowing reviewers to understand what happened.

---

## Anticipated Edge Cases

### Edge Case 1: Formal academic essay written by a human

A human student may write a formal essay with consistent sentence structure, polished transitions, and limited personal detail. The system may score the text as AI-like because both signals could produce high scores.

Potential result:

```text
sentence_uniformity_score = 0.78
specificity_genericness_score = 0.70
combined_score = 0.74
label = Likely AI-generated or heavily AI-assisted
```

Why this is difficult: The writing style may genuinely resemble AI-generated text even though the student wrote it. This is a false positive risk.

Mitigation: The label must say the result is not proof. The creator must be able to appeal and explain that the assignment required a formal tone.

---

### Edge Case 2: Poem or creative writing with repetition

A poem may intentionally repeat words, use simple vocabulary, or use short, uniform lines. The sentence uniformity signal may treat this as machine-like even though repetition is a normal creative choice.

Potential result:

```text
sentence_uniformity_score = 0.85
specificity_genericness_score = 0.55
combined_score = 0.70
label = Likely AI-generated or heavily AI-assisted
```

Why this is difficult: The system is designed mostly for prose, not poetry. Creative writing can break normal assumptions about sentence structure.

Mitigation: The system should mention that genre affects reliability. A stretch feature could allow users to specify content type before analysis.

---

### Edge Case 3: Short text message or short answer

A short response may not contain enough information to fairly analyze.

Example:

```text
Yes, I agree with this because technology helps people.
```

Why this is difficult: There are too few sentences and too few details to calculate reliable signal scores.

Mitigation: The input validator should reject very short submissions or return a low-confidence result saying there is not enough text to analyze fairly.

---

### Edge Case 4: AI-generated text with fake personal details

An AI-generated response can include names, dates, numbers, and first-person details if the prompt asks for them.

Example:

```text
When I worked at FPT Software in June 2024, I improved the dashboard speed by 25%.
```

Why this is difficult: The specificity signal may incorrectly treat fake details as human-like.

Mitigation: The system should not treat specific detail as proof of human authorship. It should only use specificity as one signal in the combined score.

---

### Edge Case 5: Non-native English writer using careful structure

A non-native English writer may write in a very structured and formal way to avoid grammar mistakes. The sentence uniformity signal may score this as AI-like.

Why this is difficult: The system may unfairly flag careful writing from English learners.

Mitigation: The transparency label should avoid accusatory wording, and appeals should allow the creator to provide context.

---

## AI Tool Plan

This planning document will be used as the main prompt source for implementation in Milestones 3-5. The goal is to give the AI tool specific sections so it generates code that matches this architecture instead of inventing its own structure.

---

### M3: Submission Endpoint + First Signal

#### Spec sections to provide to the AI tool

For Milestone 3, I will provide these sections:

- Architecture
- Detection Signals
- Signal 1: Sentence Uniformity
- API Surface: `POST /submit`
- Audit Logging Plan, submission entry only

#### What I will ask the AI tool to generate

I will ask the AI tool to generate:

1. A basic Flask app skeleton.
2. A `POST /submit` endpoint.
3. Input validation for submitted text.
4. A `calculate_sentence_uniformity(text)` function.
5. A temporary response that returns the first signal score before the full scoring system is built.

Expected function output:

```json
{
  "name": "sentence_uniformity",
  "score": 0.72,
  "explanation": "The text has highly consistent sentence lengths."
}
```

#### How I will verify the output

I will test the sentence uniformity function directly with at least three inputs.

Test 1: Uniform AI-like text

```text
Technology improves productivity in many organizations. Automation supports faster decision making across departments. Digital tools help teams complete tasks with greater efficiency.
```

Expected result:

```text
Higher sentence_uniformity_score
```

Test 2: Varied human-like text

```text
I tried it once. Honestly, it did not work the way I expected, especially when the deadline got close and our team had to change the whole plan.
```

Expected result:

```text
Lower or medium sentence_uniformity_score
```

Test 3: Too-short text

```text
I agree.
```

Expected result:

```text
Validation error or low reliability warning
```

I will check that the endpoint returns valid JSON and that the signal score stays between `0.0` and `1.0`.

---

### M4: Second Signal + Confidence Scoring

#### Spec sections to provide to the AI tool

For Milestone 4, I will provide these sections:

- Detection Signals
- Signal 1: Sentence Uniformity
- Signal 2: Specificity and Personal Detail
- Combining Signal Scores
- Uncertainty Representation
- Architecture diagram

#### What I will ask the AI tool to generate

I will ask the AI tool to generate:

1. `calculate_specificity_genericness(text)`.
2. A combined scoring function named `calculate_ai_likelihood_score(signal_1, signal_2)`.
3. Logic that returns both signal scores and the combined score in the `/submit` response.
4. Simple explanations for each signal.

Expected second signal output:

```json
{
  "name": "specificity_and_personal_detail",
  "score": 0.61,
  "explanation": "The text contains limited concrete detail."
}
```

Expected combined score output:

```json
{
  "sentence_uniformity_score": 0.72,
  "specificity_genericness_score": 0.61,
  "ai_likelihood_score": 0.67
}
```

#### How I will verify the output

I will test whether scores vary meaningfully between clearly generic AI-like text and clearly personal human-like text.

Test 1: Generic text

```text
Technology is important because it helps people improve productivity, communicate more effectively, and achieve better outcomes in modern organizations.
```

Expected result:

```text
Higher specificity_genericness_score
```

Test 2: Specific personal text

```text
In June 2024, I worked on a Django dashboard at FPT Software and helped reduce loading time by about 25% by improving how the frontend requested data.
```

Expected result:

```text
Lower specificity_genericness_score
```

Test 3: Mixed text

```text
Technology improves productivity in many organizations. In my internship at FPT Software, I saw this when our team improved a dashboard loading issue.
```

Expected result:

```text
Medium combined score
```

I will check that:

- The second signal returns a score between `0.0` and `1.0`.
- More specific text receives a lower genericness score.
- Generic text receives a higher genericness score.
- The combined score changes when signal scores change.
- The system does not use a simple binary cutoff at `0.5`.

---

### M5: Production Layer

#### Spec sections to provide to the AI tool

For Milestone 5, I will provide these sections:

- Transparency Label Design
- Appeals Workflow
- API Surface
- Audit Logging Plan
- Architecture diagram
- Anticipated Edge Cases

#### What I will ask the AI tool to generate

I will ask the AI tool to generate:

1. Label generation logic using the exact three label variants.
2. `POST /appeal` endpoint.
3. Appeal status updates.
4. Audit logging for submissions and appeals.
5. Optional `GET /submission/{submission_id}` endpoint.
6. Optional `GET /appeals` endpoint for human review.

Expected label function behavior:

```text
0.00-0.39 -> Likely human-written
0.40-0.69 -> Possibly AI-assisted
0.70-1.00 -> Likely AI-generated or heavily AI-assisted
```

#### How I will verify the output

I will test all three label variants using controlled signal values or carefully selected input text.

Test 1: Human label reachable

Expected score:

```text
0.20
```

Expected label:

```text
Likely human-written
```

Test 2: Uncertain label reachable

Expected score:

```text
0.55
```

Expected label:

```text
Possibly AI-assisted
```

Test 3: AI label reachable

Expected score:

```text
0.82
```

Expected label:

```text
Likely AI-generated or heavily AI-assisted
```

Test 4: Appeal updates status

Steps:

1. Submit text through `POST /submit`.
2. Save the returned `submission_id`.
3. Send that `submission_id` to `POST /appeal` with an appeal reason.
4. Confirm the response says:

```json
{
  "appeal_status": "appealed"
}
```

5. Check the audit log to confirm an `appeal_submitted` event was recorded.

---

## Review of Label Variants Before Implementation

The label variants are intentionally cautious. None of them says the system has proven authorship. The highest label says "Likely AI-generated or heavily AI-assisted," not "Definitely AI-generated." The uncertain range is intentionally wide because false positives can be harmful. A score of `0.60` should not be treated as likely AI. It should produce the uncertain label.

Final label thresholds before implementation:

```text
0.00-0.39 = Likely human-written
0.40-0.69 = Possibly AI-assisted
0.70-1.00 = Likely AI-generated or heavily AI-assisted
```

---

## Future Stretch Features

These features should only be added after the required system works.

### Stretch Feature 1: Content Type Selection

Allow the user to identify whether the text is an essay, poem, email, discussion post, report, or reflection. This could help reduce false positives for poetry and short-form writing.

### Stretch Feature 2: Human Review Queue

Build a reviewer dashboard that shows appealed submissions, signal scores, original labels, appeal reasons, and reviewer decisions.

### Stretch Feature 3: Improved Signal Weighting

Adjust the signal weights after testing. For example, specificity might be weighted more heavily than sentence uniformity if sentence uniformity creates too many false positives.

Possible future formula:

```text
ai_likelihood_score = (sentence_uniformity_score * 0.40) + (specificity_genericness_score * 0.60)
```

### Stretch Feature 4: Minimum Text Reliability Rating

Add a separate reliability score based on text length. Short texts should not receive strong labels because there is not enough evidence.

---

## Checkpoint Summary

This planning document answers the five required planning questions. The system uses two detection signals: sentence uniformity and specificity/personal detail. Each signal returns a score between `0.0` and `1.0`, plus an explanation. The scores are combined into a single AI-likelihood confidence score using a weighted average.

Uncertainty is represented through three score ranges, not a binary cutoff. Scores from `0.00-0.39` produce a likely human label. Scores from `0.40-0.69` produce an uncertain or possibly AI-assisted label. Scores from `0.70-1.00` produce a likely AI-generated or heavily AI-assisted label.

The three transparency label variants have been written out before implementation. Each label includes cautious wording and reminds the user that the result is an estimate, not proof.

The appeals workflow allows a creator to appeal a label by submitting a submission ID, appeal reason, and optional supporting context. The system updates the appeal status, logs the event, and allows a human reviewer to inspect the original label, signal scores, explanation, and appeal reason.

The architecture section includes both the submission flow and appeal flow. The AI Tool Plan explains how this spec will be used in Milestones 3, 4, and 5 to generate implementation code and verify that each part works correctly.
