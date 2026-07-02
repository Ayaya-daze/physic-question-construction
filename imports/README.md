# Agent Import Inbox

Humans drop source material here. Codex agents process it with the
`physics-question-importer` skill and finalize it into the file-first question
bank.

```text
imports/
  inbox/   # human drop zone
  jobs/    # active agent jobs
  done/    # finalized jobs
  failed/  # failed finalization attempts
```

Recommended source bundle:

```text
imports/inbox/2026-physics-set-03/
  source.pdf
  answers.pdf
  notes.md          # optional human notes
  assets/           # optional independent figures, not rendered full pages
```

Direct structured import bundle:

```text
imports/inbox/ready-batch/
  questions.json
  assets/
```

Commands:

```bash
python3 skills/physics-question-importer/scripts/agent_inbox.py --project-root . init
python3 skills/physics-question-importer/scripts/agent_inbox.py --project-root . run
python3 skills/physics-question-importer/scripts/agent_inbox.py --project-root . status
```

If a job needs vision/manual work, open its `AGENT_TASK.md`, write
`output/questions.json`, then run:

```bash
python3 skills/physics-question-importer/scripts/agent_inbox.py --project-root . finalize
```
