# Skill Interface

Purpose: let an external vision/LLM workflow turn PDFs, page images, OCR text, or corrected text into the project's file-first question records.

## Contract

Backend handles rendering, file I/O, and index rebuild. The skill/model returns simple records:

```json
[
  {
    "question_body": "1.（40分）... $F=ma$ ...",
    "answer_body": "",
    "metadata": {
      "title": "短标题",
      "knowledge_points": ["力学"],
      "source_pages": [1],
      "human_review_needed": false
    }
  }
]
```

`question_body` and `answer_body` are Markdown/LaTeX text. Do not output options, choices, solution steps, or other hardcoded schemas.

## Scanned PDF Rule

Rendered page images are the source of truth. OCR text is only a hint. Text-only LLMs can clean text that OCR captured, but cannot recover missed problem numbers, formulas, figures, or page-boundary context.

Use a vision model for production scanned-paper import. If no vision/manual transcription is available, do not import raw OCR or full-page images as production questions.

## Splitting Rules

- Split only major problem numbers such as `1.`, `2.`, `7.(40分)`.
- Keep subparts `(1)(2)(3)` and `①②③` inside the parent problem.
- Merge cross-page continuations.
- Treat declared counts and OCR-detected numbers as weak hints.
- Return the visible/readable problems; do not pad/drop/merge to match a count.
- Whole rendered pages are evidence, not `assets/`. Use only cropped/independent figures as question assets.

## Backend Payload Shape

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

The detailed reusable Codex skill lives at `~/.codex/skills/physics-question-importer`.
