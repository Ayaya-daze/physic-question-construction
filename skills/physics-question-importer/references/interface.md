# Interface Reference

Use this only when wiring the backend or calling a model directly.

## Input

```json
{
  "source_filename": "paper.pdf",
  "paper_metadata": {
    "title": "optional",
    "total_problems": 7,
    "total_score": 320,
    "possible_problem_numbers": [1, 2, 3]
  },
  "pages": [
    {"page_num": 1, "image_path": "rendered/page_001.png", "ocr_text": "..."}
  ]
}
```

For scanned PDFs, `image_path` is authoritative. `ocr_text`, counts, and detected numbers are hints only.

## Prompt Skeleton

```text
Import this scanned physics paper into simple question files.

Hints:
- title: {title}
- total_problems: {total_problems}
- total_score: {total_score}
- OCR numbers: {possible_problem_numbers}

Rules:
- Read page images as source of truth; OCR is auxiliary.
- Split only visible major problems like 1. / 2. / 7.(40分).
- Keep subparts inside the parent problem and merge cross-page continuations.
- Do not force output count to match hints.
- Markdown body, LaTeX math as $...$ or $$...$$.
- answer_body only for explicit source answers.
- Full rendered pages are recognition evidence, not question assets.
- Mark uncertain text or missing uncropped figures with human_review_needed=true.

Return strict JSON array:
[{"question_body":"... ![diagram](assets/diagram.png)","answer_body":"","metadata":{"title":"...","knowledge_points":["..."],"source_pages":[1],"human_review_needed":false}}]

OCR hints:
{combined_text}
```

Put cropped/independent figure files under `assets/` next to the JSON. Never reference rendered full-page images.

## Output

Each item needs:

- `question_body`: non-empty Markdown/LaTeX text.
- `answer_body`: string, usually empty.
- `metadata.title`: short title.
- `metadata.knowledge_points`: discovered concepts, when possible.
- `metadata.source_pages`: source page numbers, when known.
- `metadata.human_review_needed`: true for uncertain records.

Validate with `scripts/validate_output.py` before writing files.
