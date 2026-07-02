# CLAUDE.md

Repository guidance for agents working on this project.

## Product Contract

This is a file-first physics question bank. The production source of truth is:

```text
questions/<id>/
  question.md|tex|txt
  answer.md|tex|txt
  metadata.yaml
  assets/
```

The vector index under `questions/.index/` is rebuildable. SQLite/SQLAlchemy models and legacy structured APIs remain only for compatibility, review experiments, or old fixtures. Do not move the main path back to hardcoded choices/options/solution-step schemas.

Knowledge points are discovered from imported questions and human edits. Seed files under `data/` are examples, not production truth.

## Main Flow

- Import sources into `question.*`, `answer.*`, optional assets, and loose metadata.
- Render question bodies as Markdown/LaTeX in the frontend.
- Rebuild/search the local file index from the question files.
- Generate papers by concatenating selected question/answer bodies into TeX templates.
- Export separate files: `questions.tex/pdf` and `answers.tex/pdf`.

Scanned PDF page renders are OCR/vision evidence only. They must not become fallback question images or paper content. Real figure assets must be cropped/independent images referenced by the body files.

## Key Files

```text
backend/app/api/file_questions.py           # file-question API and TeX/PDF export
backend/app/services/file_question_store.py # file store, index, search
backend/app/services/file_question_importer.py
frontend/src/app/questions/                 # file-question UI
frontend/src/app/papers/generator/          # file-first paper generation UI
frontend/src/components/QuestionBodyRenderer.tsx
questions/                                  # production question files
docs/                                       # current architecture and acceptance notes
```

Legacy structured modules such as `backend/app/api/questions.py`, `backend/app/services/latex_renderer.py`, and `backend/app/models/question.py` may still exist. Treat them as compatibility code unless the task explicitly targets them.

## Local Run

```bash
cd backend
venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
cd frontend
npm run dev
```

Use frontend `:3000`, backend `:8000`, API docs `:8000/docs`.

For production-style frontend preview:

```bash
cd frontend
npm run build
NODE_ENV=production PORT=3001 BACKEND_URL=http://127.0.0.1:8000 npm run start
```

Do not use backend `--reload` during upload/import tests; file writes can interrupt in-flight requests.
