# Agent Inbox 导入工作流

## 目标

让人类只做一件事：把原始资料放进 `imports/inbox/`。

系统和 agent 自动完成：

1. 扫描 inbox。
2. 创建标准导入 job。
3. 为每个 job 生成 `AGENT_TASK.md`。
4. 对已经是结构化 JSON 的资料自动校验；高风险记录停在审核状态。
5. 对 PDF/扫描件交给 Codex agent + `physics-question-importer` skill 读页、拆题、写 JSON。
6. 自动校验 skill 输出。
7. 只有明确通过审核的记录才原子写入 `questions/{id}/question.md`、`answer.md`、`metadata.yaml`、`assets/*`。
8. 重建 FTS5、向量和动态知识点索引。

## 目录结构

```text
imports/
  inbox/   # 人类投放原始文件或文件夹
  jobs/    # 待 agent 处理或待 finalize 的任务
  done/    # 已入库归档
  failed/  # 入库失败归档
```

推荐人类投放一个文件夹，而不是把多个相关文件散放在 inbox 根目录：

```text
imports/inbox/第3套/
  source.pdf
  answers.pdf
  notes.md
  assets/
```

如果已经由人工或外部模型整理成结构化题目：

```text
imports/inbox/第3套-ready/
  questions.json
  assets/
```

`questions.json` 格式：

```json
[
  {
    "question_body": "1.（40分）... $F=ma$ ...",
    "answer_body": "",
    "metadata": {
      "title": "短标题",
      "knowledge_points": ["力学"],
      "source_pages": [1],
      "human_review_needed": true
    }
  }
]
```

## 命令

初始化目录：

```bash
python3 skills/physics-question-importer/scripts/agent_inbox.py --project-root . init
```

扫描 inbox 并自动 finalize 已完成输出：

```bash
python3 skills/physics-question-importer/scripts/agent_inbox.py --project-root . run
```

查看状态：

```bash
python3 skills/physics-question-importer/scripts/agent_inbox.py --project-root . status
```

只扫描新文件：

```bash
python3 skills/physics-question-importer/scripts/agent_inbox.py --project-root . discover
```

只入库已完成的 job：

```bash
python3 skills/physics-question-importer/scripts/agent_inbox.py --project-root . finalize
```

若输出标记需要人工审核，命令会把 job 状态设为 `needs_review`。对照来源确认完成后，显式批准：

```bash
python3 skills/physics-question-importer/scripts/agent_inbox.py --project-root . finalize --approve-review
```

本项目也保留兼容包装：

```bash
PYTHONPATH=backend backend/venv/bin/python backend/scripts/agent_inbox.py run
```

## Agent 处理方式

`discover` 会把 inbox 项移动到：

```text
imports/jobs/{job_id}/
  source/
  output/
    assets/
  manifest.json
  AGENT_TASK.md
```

agent 打开 `AGENT_TASK.md`，使用 `physics-question-importer` skill，输出：

```text
imports/jobs/{job_id}/output/questions.json
imports/jobs/{job_id}/output/assets/*
```

然后运行：

```bash
python3 skills/physics-question-importer/scripts/agent_inbox.py --project-root . finalize
```

无风险输出可直接完成；包含 `human_review_needed: true` 的输出不会自动入库。批准后 job 才进入 `imports/done/`，题目进入 `questions/`，索引自动重建。

## 自动化边界

- Markdown/LaTeX/TXT 或已经整理好的 `questions.json` 可以高度自动化。
- 扫描 PDF/图片会自动建 job，但读图、拆题、确认题号和公式仍由 Codex agent + vision 能力完成。
- CnOcr/text-only LLM 不能恢复 OCR 没读到的题号、公式、图或跨页边界。
- 整页 PDF 渲染图只能作为识别证据，不能作为题目资产入库。
- 题图必须是独立图或裁剪后的局部图，放到 `output/assets/` 并由 Markdown 引用。
