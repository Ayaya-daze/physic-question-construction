# 项目审查与整理记录

日期：2026-07-02

## 结论

当前项目应按文件题库交付，而不是按旧的硬编码题型数据库交付。

生产主线：

```text
imports/inbox/ 或前端上传
  -> Codex physics-question-importer / vision LLM / 人工校对
  -> questions/{id}/question.md
  -> questions/{id}/answer.md
  -> questions/{id}/metadata.yaml
  -> questions/{id}/assets/*
  -> questions/.index/vector-index.json
  -> /papers/generator 导出 questions.tex/pdf 和 answers.tex/pdf
```

旧结构化模块仍保留为兼容层，包括：

- `backend/app/api/questions.py`
- `backend/app/api/papers.py`
- `backend/app/api/review.py`
- `backend/app/models/question.py`
- `frontend/src/app/review/*`
- `frontend/src/app/papers/[paperId]/*`
- `frontend/src/app/questions/[id]/*`

这些路径不作为默认生产入口。维护时不能把题库主模型改回 `question_type`、`options`、`solution_steps` 这类固定结构。

## 本次整理

- 首页统计改为读取文件题库统计 `/api/file-questions/stats`。
- `/questions` 改为文件题库列表，进入 `/questions/files/{id}`。
- 侧边栏只保留生产主线：首页、题库、组卷、导入资料。
- `/papers` 改为跳转到 `/papers/generator`，避免用户进入旧结构化组卷页。
- `/papers/generator` 返回链接改到文件题库。
- `.gitignore` 补充忽略根目录 SQLite DB、运行导出、临时输出、Playwright 日志、渲染页等可再生产物。
- README、CLAUDE、组卷文档同步为 `/papers/generator` 和文件题库口径。
- 单用户大批量上传改为后台导入 job：`/upload` 提交后立即返回，`backend/uploads/file-import-jobs/{job_id}/manifest.json` 记录进度，后端单 worker 顺序处理并在任务结束后统一重建索引。

## 目录口径

应保留并视为项目有效数据：

- `questions/`：当前题库真源。
- `imports/`：人类投放和 agent 导入队列。
- 根目录 `第1套+.pdf`、`第1套+答案解析.pdf`、`第1套_人工校对文字版.txt`、`第2套+.pdf`、`第2套+答案解析.pdf`：当前测试源资料，未移动。

可重建或运行时产物：

- `backend/exports/`
- `backend/uploads/`
- `backend/uploads/file-import-jobs/`：后台导入任务运行记录；已完成/失败的旧任务可清理。
- `tmp/`
- `output/`
- `rendered-pages/`
- `.playwright-cli/`
- `physics_questions.db*`
- `frontend/.next/`
- `frontend/node_modules/`
- `.venv/`
- `backend/venv/`

这些目录和文件不应作为题库真源。

## 已验收命令

```bash
PYTHONPATH=backend backend/venv/bin/python -m py_compile backend/app/api/file_questions.py
```

```bash
cd frontend
npm run build
```

```bash
PYTHONPATH=backend backend/venv/bin/python - <<'PY'
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
assert client.get('/api/file-questions/stats').status_code == 200
assert client.get('/api/file-questions?limit=5').status_code == 200
assert client.get('/api/file-questions/qf_prod_e2e_set1_q1').status_code == 200

res = client.post('/api/file-questions/papers/export', json={
    'title': '项目整理验收卷',
    'question_ids': ['qf_prod_e2e_set1_q1', 'qf_prod_e2e_set2_q2'],
    'question_count': 2,
})
assert res.status_code == 200
data = res.json()
export_dir = Path('backend/exports/file-papers') / data['export_id']
assert (export_dir / 'questions.tex').exists()
assert (export_dir / 'answers.tex').exists()
assert (export_dir / 'questions.pdf').exists()
assert (export_dir / 'answers.pdf').exists()
PY
```

本次实际生成的导出：

```text
backend/exports/file-papers/filepaper_20260702_043155_7a5eeef4/
  questions.tex
  questions.pdf
  answers.tex
  answers.pdf
```

浏览器冒烟验收：

```text
后端：http://127.0.0.1:8000
前端：http://127.0.0.1:3001
页面：/、/questions、/papers、/upload
结果：全部可打开；/papers 正确跳转 /papers/generator；无 4xx 响应；无 console error。
截图：output/playwright/project-review-3001-*.png
```

## 剩余风险

- 扫描 PDF 的自动导入仍取决于 vision-capable agent 或人工校对；CnOcr/text-only LLM 不能恢复漏掉的题号、公式和图。
- 文件题库已有样例题仍需要人审准确性。
- 当前本地向量索引是轻量实现，生产大规模题库可替换为外部向量库，但索引仍应可从 `questions/` 重建。
- 项目没有认证和权限控制，不应直接公网暴露。
- 旧结构化页面仍在代码中，后续如果继续精简，可做一次兼容层隔离或归档。
