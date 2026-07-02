---
name: physics-question-importer
description: "Convert physics PDFs, scanned pages, OCR text, corrected source text, or agent inbox drops into a file-first question-bank format. Use for OCR proofreading, vision-first scanned-paper splitting, preserving Markdown/LaTeX math, separating explicit answers, attaching real question assets, processing imports/inbox jobs, and producing question.md / answer.md / metadata.yaml records."
---

# Physics Question Importer

## Contract

Write simple records only:

```text
questions/<id>/
  question.md
  answer.md          # empty/omitted unless source has an answer
  metadata.yaml
  assets/            # cropped/independent figures only
```

Do not invent core schemas for options, choices, solution steps, or subparts. Put them in `question.md` or `answer.md`.

## Workflow

1. Inspect the source. For PDFs/scans, render pages and read page images; OCR is only a hint.
2. Use a vision model for scanned papers when correctness matters. Text-only LLMs cannot recover missed numbers, formulas, or figures.
3. Split only on visible major problem numbers (`1.`, `2.`, `7.(40分)`). Keep `(1)(2)(3)` and `①②③` inside the parent problem.
4. Treat declared counts and OCR-found numbers as weak hints. Return the problems actually visible/readable; never pad or merge to match a count.
5. Preserve Markdown text with LaTeX math delimiters: `$...$` or `$$...$$`.
6. Write answers only when explicitly present in the source.
7. Do not store rendered whole PDF pages as question assets. If a figure is needed but not cropped, mark `human_review_needed: true`.
8. Validate JSON before materializing records.

Read `references/interface.md` only when you need the backend payload shape or a prompt skeleton.

## Agent Inbox

For projects that use a human drop zone such as `imports/inbox`, use the bundled inbox manager instead of rewriting directory plumbing:

```bash
python3 ~/.codex/skills/physics-question-importer/scripts/agent_inbox.py --project-root /path/to/project init
python3 ~/.codex/skills/physics-question-importer/scripts/agent_inbox.py --project-root /path/to/project run
python3 ~/.codex/skills/physics-question-importer/scripts/agent_inbox.py --project-root /path/to/project status
```

The inbox manager creates jobs under `imports/jobs/{job_id}/`, writes `AGENT_TASK.md`, auto-finalizes already valid `questions.json` bundles, and materializes completed `output/questions.json` records into `questions/`. If a job contains PDF/scanned sources, read its `AGENT_TASK.md`, produce `output/questions.json` and optional `output/assets/*`, then run:

```bash
python3 ~/.codex/skills/physics-question-importer/scripts/agent_inbox.py --project-root /path/to/project finalize
```

## Output JSON

If a record references cropped figures, put files under `assets/` next to the JSON and reference them as Markdown images. Do not reference rendered full pages.

```json
[
  {
    "question_body": "1.（40分）... $F=ma$ ...\n\n![diagram](assets/diagram.png)",
    "answer_body": "",
    "metadata": {
      "title": "短标题",
      "knowledge_points": ["力学", "小振动"],
      "source_pages": [1, 2],
      "human_review_needed": false
    }
  }
]
```

## Scripts

```bash
python3 ~/.codex/skills/physics-question-importer/scripts/validate_output.py output.json
python3 ~/.codex/skills/physics-question-importer/scripts/materialize_questions.py output.json --questions-dir ./questions --source-name "source.pdf"
python3 ~/.codex/skills/physics-question-importer/scripts/agent_inbox.py --project-root . run
```

After materializing into the app, rebuild the file-question index.
