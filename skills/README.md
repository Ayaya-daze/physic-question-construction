# Bundled Codex Skills

This repository includes the project-specific Codex skill used for production imports:

```text
skills/physics-question-importer/
```

It converts physics PDFs, scans, OCR text, corrected text, and `imports/inbox` drops into the file-first question-bank format:

```text
questions/{id}/question.md
questions/{id}/answer.md
questions/{id}/metadata.yaml
questions/{id}/assets/*
```

Use it directly from the repository:

```bash
python3 skills/physics-question-importer/scripts/agent_inbox.py --project-root . run
```

Or install it into a Codex user environment:

```bash
mkdir -p ~/.codex/skills
cp -R skills/physics-question-importer ~/.codex/skills/
```

The skill deliberately refuses to treat rendered whole PDF pages as question assets. Scanned PDF imports should be handled with a vision-capable agent/model and then validated as `questions.json` plus independent cropped assets.

