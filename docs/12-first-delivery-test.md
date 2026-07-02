# 第一次交付测试说明

日期：2026-07-02

## 交付范围

本次交付按文件题库主线验收：

```text
题目资料
  -> 导入任务或 agent/skill 整理
  -> questions/{id}/question.md
  -> questions/{id}/answer.md
  -> questions/{id}/metadata.yaml
  -> questions/{id}/assets/*
  -> questions/.index/vector-index.json
  -> 浏览器查看题目
  -> 组卷导出 questions.tex/pdf 和 answers.tex/pdf
```

题库内部不使用固定题型结构作为生产真源。选择题选项、解析、小问、标签等内容如果存在，直接写入 `question.md`、`answer.md` 或松散 `metadata.yaml`。

## 启动

后端：

```bash
cd /Users/ayaya/Documents/Codex/physics-question-bank/backend
venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端开发入口：

```bash
cd /Users/ayaya/Documents/Codex/physics-question-bank/frontend
npm run dev
```

浏览器访问：

```text
http://localhost:3000
```

生产预览入口：

```bash
cd /Users/ayaya/Documents/Codex/physics-question-bank/frontend
npm run build
NODE_ENV=production PORT=3001 BACKEND_URL=http://127.0.0.1:8000 npm run start
```

浏览器访问：

```text
http://localhost:3001
```

## 测试流程

1. 打开首页，确认统计来自文件题库。
2. 打开“题库”，确认列表能加载并能进入 `/questions/files/{id}`。
3. 打开题目详情，确认 Markdown、LaTeX 公式、答案和图片资产能显示。
4. 打开“导入资料”，提交一批 Markdown/JSON/图片资料，观察后台 job 进度。
5. 对扫描 PDF，未配置 vision LLM 时应明确失败，不应把整页 PDF 渲染图当成题目资产入库。
6. 导入后重建索引或等待 job 完成后自动重建索引。
7. 打开“组卷”，手动选题或用知识点/搜索词召回题目。
8. 导出试卷，确认生成两套文件：
   - `questions.tex`
   - `questions.pdf`
   - `answers.tex`
   - `answers.pdf`
9. 下载 PDF，确认题目卷不包含答案，答案卷只作为参考答案。
10. 有图片的题目应在题目 PDF 中显示独立题图，而不是原始整页 PDF。

## Agent/Skill 导入

人类批量投放资料时，把文件放入：

```text
imports/inbox/
```

运行：

```bash
python3 ~/.codex/skills/physics-question-importer/scripts/agent_inbox.py --project-root /Users/ayaya/Documents/Codex/physics-question-bank run
```

如果 job 里是已经整理好的 `questions.json` 和独立图片资产，脚本会自动入库。如果 job 里是扫描 PDF，需要 Codex agent 使用 `physics-question-importer` skill 读取 `AGENT_TASK.md`，输出 `output/questions.json` 和可选 `output/assets/*`，再运行：

```bash
python3 ~/.codex/skills/physics-question-importer/scripts/agent_inbox.py --project-root /Users/ayaya/Documents/Codex/physics-question-bank finalize
```

原则：

- OCR 文本只能作为提示，不是扫描卷生产真源。
- Vision-capable LLM 或 agent 读图后产出的 Markdown/LaTeX 题目文本才可进入题库。
- 整页 PDF 渲染图只能作为识别证据，不能作为正式题图资产。
- 题图必须是独立裁剪图片，并通过 Markdown 图片语法引用。

## 已完成压力验收

最近一次极端压力测试报告：

```text
output/stress-extreme-rerun-report.json
```

覆盖结果：

- 后端关键文件 Python 编译通过。
- 前端 `npm run build` 通过。
- 隔离临时题库导入 `740` 道题成功。
- 覆盖重复 ID、缺失资产、整页 PDF 渲染图伪资产、坏 PNG、超大文件、扫描 PDF 无 vision、坏 metadata、坏向量索引。
- 搜索、分页、资产读取、索引重建通过。
- 组卷导出 `200` 题通过，题目卷 `78` 页，答案卷 `26` 页。
- PDF 内检测到真实图片资产，图片页渲染正常。

关键产物：

```text
output/stress-extreme-rerun-questions.pdf
output/stress-extreme-rerun-answers.pdf
output/pdf/stress-extreme-rerun-questions-p1.png
output/pdf/stress-extreme-rerun-answers-p1.png
output/pdf/stress-extreme-rerun-questions-image-page.png
```

## 交付限制

- 当前定位为单用户本地/内网工具，不包含账号、权限和公网安全。
- 后台导入是单 worker 队列，适合一个操作者大批量资料导入，不适合多用户并行抢任务。
- 扫描 PDF 的自动拆题依赖 vision-capable LLM 或 Codex agent；未配置时失败是正确行为。
- 本地向量索引是轻量实现，可从 `questions/` 重建；未来可替换为真实 embedding/向量库。
- 旧结构化数据库和页面仍作为兼容层存在，不是本次交付入口。

## 交付前命令

```bash
cd /Users/ayaya/Documents/Codex/physics-question-bank
PYTHONPATH=backend backend/venv/bin/python -m py_compile \
  backend/app/services/file_question_store.py \
  backend/app/services/file_question_importer.py \
  backend/app/services/file_import_jobs.py \
  backend/app/api/file_questions.py \
  backend/app/main.py
```

```bash
cd /Users/ayaya/Documents/Codex/physics-question-bank/frontend
npm run build
```

清理检查只做 dry-run：

```bash
cd /Users/ayaya/Documents/Codex/physics-question-bank/backend
venv/bin/python scripts/cleanup_runtime_artifacts.py
```
