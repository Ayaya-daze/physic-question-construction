# Physics Question Bank

一个文件优先的物理题库系统。当前目标不是做复杂题型数据库，而是先交付稳定可用的基本闭环：存题、看题、索引、搜索、组卷、导出 TeX/PDF。

## 当前验收口径

- 题库真源是文件系统：每道题一个目录。
- 题目正文、答案、图片资产直接从文件读取。
- 题目正文格式可用 Markdown、LaTeX 或纯文本；TeX 只是最终组卷导出的目标格式。
- 前端题目详情支持正文、答案、图片和 LaTeX 数学公式渲染。
- 本地向量索引从题目文件重建，用于搜索和组卷候选召回。
- 组卷 MVP 支持用户手动选题，或输入相关知识点/搜索词和题目数自动选题。
- 组卷导出必须分别生成题目卷和答案卷：题目卷只含题目，答案卷只含答案。
- 题目卷和答案卷都必须输出 TeX 源文件；本地有 LaTeX 环境时分别编译 PDF。
- 大批量导入使用后台单 worker job，浏览器只提交任务和查看进度。

旧的结构化数据库、题型、选项、解析步骤等代码仍保留为兼容层，不是当前题库主模型。

当前验收结论见 [docs/08-acceptance-and-required-changes.md](docs/08-acceptance-and-required-changes.md)，本次项目整理记录见 [docs/10-project-review-and-organization.md](docs/10-project-review-and-organization.md)，第一次交付测试说明见 [docs/12-first-delivery-test.md](docs/12-first-delivery-test.md)。

完整文档索引见 [docs/README.md](docs/README.md)。三套参考项目的审查与采用决策见 [docs/13-reference-project-review.md](docs/13-reference-project-review.md)；项目参赛定位、量化指标、六周实施节奏和现场演示方案见 [docs/14-competition-project-plan.md](docs/14-competition-project-plan.md)。

## 当前基线与比赛目标

| 能力 | 当前仓库 | 比赛目标 |
| --- | --- | --- |
| 文件题库 | 简单结构、稳定 ID、全量预检、原子目录提交和中断恢复已完成 | 增加脱敏真值集和更大规模验证 |
| Markdown/LaTeX/图片显示 | 正式题目与审核候选均可编辑和预览 | 增加来源区域对照与局部裁图 |
| 题目卷/答案卷 TeX/PDF | 独立导出、manifest 和题目级编译错误定位已完成 | 增加候选替换、排序和评测 |
| 单用户后台批量任务 | 已完成 | 增加页级恢复、缓存和调用量统计 |
| 扫描资料识别 | Skill/视觉 Agent 或视觉 API 生成候选，阻断式人工复核 | 自研证据块、页级调度和选择性视觉 API |
| 知识点 | 从正式题目 metadata 动态生成，支持改名、合并和筛题 | 增加确认、删除和质量评测 |
| 检索 | SQLite FTS5 + 本地 float32 向量 + RRF；可选 embedding API | 建立检索真值集并量化效果 |
| Codex Skill | 已内置，可处理人工批次 | 开发维护和质量对照，不是比赛运行依赖 |

当前压力测试已覆盖 24 项极端用例、隔离环境 740 题导入和 200 题组卷。这证明文件存储、索引重建和组卷导出主链路可承压，不代表扫描识别准确率已经达到比赛目标。

## 文件题库结构

```text
questions/
  sample-file-question/
    question.md        # 题目正文，支持 Markdown/LaTeX 数学/图片引用
    answer.md          # 答案正文，支持同样格式
    metadata.yaml      # 可选松散元数据，不作为核心结构
    assets/
      diagram.png
  .index/
    lexical.sqlite       # SQLite FTS5/BM25
    vectors.f32          # 本地 float32 向量
    vector-map.json      # 题目与向量偏移
    index-manifest.json  # 模型、维度和索引哈希
    vector-index.json    # 兼容入口
    knowledge-points.json
```

支持的正文文件名：

- `question.md` / `question.tex` / `question.txt`
- `answer.md` / `answer.tex` / `answer.txt`
- 兼容旧文件：`content.md` / `content.tex` / `content.txt`

题目内部核心只分两块：题目正文和答案正文。选项、解析、小问等如果需要，直接写在正文或答案文本里，不拆成硬编码字段。

## 组卷逻辑

当前组卷不是按复杂结构文件拼装，而是：

1. 从文件题库读取题目正文和答案正文。
2. 手动选题，或用搜索词/知识点从向量索引召回题目。
3. 把选中的题目正文转换或原样纳入题目卷 LaTeX 模板。
4. 把对应答案正文转换或原样纳入答案卷 LaTeX 模板；没有答案时在答案卷标记“未提供答案”。
5. 复制题目资产到导出目录。
6. 用 XeLaTeX 分别编译题目卷 PDF 和答案卷 PDF。

验收目标导出目录：

```text
backend/exports/file-papers/{export_id}/
  questions.tex
  questions.pdf
  answers.tex
  answers.pdf
  build-questions.log
  build-answers.log
  manifest.json
  assets/
```

如果题目正文里引用了图片，例如：

```markdown
![block force diagram](assets/diagram.png)
```

导出的 `questions.tex` 和需要时的 `answers.tex` 会引用导出目录中的图片副本，PDF 中应能看到题图。

如果 OCR/LLM 已经产出可用的 Markdown/LaTeX 题目文本，组卷应拼接这些文本生成 TeX。扫描 PDF/图片没有可靠文本时不应写入正式题库；整页页面渲染图只作为 OCR/多模态识别证据，不能作为题目正文或题图资产降级入库，也不能把原始 PDF 简单拼接成试卷。题图必须是独立上传图片或从页面人工/程序裁剪出的局部资产。

## 启动方式

### 本地开发

```bash
cd backend
venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
cd frontend
npm run dev
```

访问：

- 前端：http://localhost:3000
- 后端 API：http://localhost:8000
- API 文档：http://localhost:8000/docs

生产预览可用：

```bash
cd frontend
npm run build
NODE_ENV=production PORT=3001 BACKEND_URL=http://127.0.0.1:8000 npm run start
```

### Docker 生产部署

```bash
docker compose up --build -d
```

Docker Compose 使用生产启动方式：

- 后端：`uvicorn app.main:app`，不启用 `--reload`。
- 前端：`npm run build` 后用自定义 `server.js` 启动，不跑 `next dev`。
- 前端容器通过 `BACKEND_URL=http://backend:8000` 代理 `/api/*`。
- 题库、导出和上传目录分别挂载到持久卷：
  - `/data/questions`
  - `/data/exports`
  - `/data/uploads`

部署时不要在运行中的前端进程下面直接覆盖 `.next`。如果重建了前端，必须重启前端服务，否则浏览器可能请求到旧 chunk。

### 运行时清理

旧导出和导入临时文件不会自动删除。先 dry-run：

```bash
cd backend
venv/bin/python scripts/cleanup_runtime_artifacts.py
```

确认后删除：

```bash
cd backend
venv/bin/python scripts/cleanup_runtime_artifacts.py --delete
```

保留天数由 `EXPORT_RETENTION_DAYS` 和 `UPLOAD_RETENTION_DAYS` 控制。

### LLM/Skill 导入

当前基线中，扫描 PDF 可由 vision-capable LLM 或 Codex `physics-question-importer` Skill 整理为候选题目，再通过 `/api/file-questions/import` 导入 JSON 和独立图片资产。该路径适合开发、人工批次修复和质量对照，结果必须复核。Text-only DeepSeek/CnOcr 只能作为草稿提示，不能作为扫描卷生产真源。

比赛目标不要求安装 Codex Agent 或完整第三方 OCR 系统。运行时由项目自行完成拆页、调度、缓存、边界识别、答案匹配、质量门和入库，只把视觉识别和 embedding 作为可替换 API。

### Agent Inbox 自动导入

项目已经内置配套 Codex skill：

```text
skills/physics-question-importer/
```

可以直接从仓库运行，也可以复制到 `~/.codex/skills/physics-question-importer` 作为全局 Codex skill 使用。

人类可以把原始资料放入：

```text
imports/inbox/
```

然后运行：

```bash
python3 skills/physics-question-importer/scripts/agent_inbox.py --project-root . run
```

脚本会自动创建标准 job、生成 `AGENT_TASK.md`、自动入库已经整理好的 `questions.json`，并对需要读图的 PDF/扫描件交给 Codex agent + `physics-question-importer` skill 处理。完成输出后运行：

```bash
python3 skills/physics-question-importer/scripts/agent_inbox.py --project-root . finalize
```

包含 `human_review_needed: true` 的输出会停在 `needs_review`，不会写入正式题库。人工对照来源确认无误后，再显式执行 `finalize --approve-review`。

项目也保留了兼容包装命令：`PYTHONPATH=backend backend/venv/bin/python backend/scripts/agent_inbox.py run`。

详细说明见 [docs/09-agent-inbox-workflow.md](docs/09-agent-inbox-workflow.md)。

### 浏览器后台批量导入

单用户大批量资料导入走 `/upload` 的后台 job 模式。提交后页面会显示 job id 和处理进度，后端按单 worker 顺序处理文件，任务结束后统一重建索引。

详细说明见 [docs/11-single-user-bulk-import.md](docs/11-single-user-bulk-import.md)。

## 主要 API

| 方法 | 路径 | 功能 |
|------|------|------|
| `GET` | `/api/file-questions` | 列出/搜索文件题库 |
| `GET` | `/api/file-questions/stats` | 读取文件题库统计 |
| `POST` | `/api/file-questions` | 创建题目文件 |
| `POST` | `/api/file-questions/upload` | 上传题目正文、答案和资产 |
| `POST` | `/api/file-questions/import/jobs` | 创建后台大批量导入任务 |
| `GET` | `/api/file-questions/import/jobs` | 列出后台导入任务 |
| `GET` | `/api/file-questions/import/jobs/{job_id}` | 查看后台导入任务状态 |
| `GET` | `/api/file-questions/import/candidates` | 列出阻断式待审核候选 |
| `POST` | `/api/file-questions/import/candidates/{id}/approve` | 批准候选并原子提交正式题库 |
| `POST` | `/api/file-questions/import/candidates/{id}/reject` | 驳回候选 |
| `GET` | `/api/file-questions/knowledge-points` | 读取从正式题目派生的知识点 |
| `PATCH` | `/api/file-questions/knowledge-points/{id}` | 改名并保留旧名作为别名 |
| `POST` | `/api/file-questions/knowledge-points/merge` | 合并知识点 |
| `POST` | `/api/file-questions/reindex` | 从题目文件重建本地向量索引 |
| `GET` | `/api/file-questions/{id}` | 读取题目正文、答案和资产列表 |
| `GET` | `/api/file-questions/{id}/assets/{name}` | 读取题目资产 |
| `POST` | `/api/file-questions/papers/export` | 文件题库组卷并导出题目卷/答案卷 TeX/PDF |
| `GET` | `/api/file-questions/papers/exports/{export_id}/questions.tex` | 下载题目卷 TeX |
| `GET` | `/api/file-questions/papers/exports/{export_id}/questions.pdf` | 下载题目卷 PDF |
| `GET` | `/api/file-questions/papers/exports/{export_id}/answers.tex` | 下载答案卷 TeX |
| `GET` | `/api/file-questions/papers/exports/{export_id}/answers.pdf` | 下载答案卷 PDF |
| `GET` | `/api/file-questions/papers/exports/{export_id}/build-questions.log` | 查看题目卷编译日志 |
| `GET` | `/api/file-questions/papers/exports/{export_id}/build-answers.log` | 查看答案卷编译日志 |
| `GET` | `/api/file-questions/papers/exports/{export_id}/manifest.json` | 下载可追溯导出清单 |

## 项目结构

```text
physics-question-bank/
  questions/                         # 当前题库真源
  backend/
    app/
      api/file_questions.py          # 文件题库 API 和 TeX/PDF 导出
      services/file_question_store.py # 文件读取、写入、索引、搜索
      services/file_question_candidates.py # 阻断式审核候选
      services/file_knowledge_points.py # 动态知识点派生和治理
    tests/test_file_first_production.py
  frontend/
    src/app/questions/               # 文件题库列表和详情
    src/app/papers/generator/        # 文件题库组卷工作台
    src/components/QuestionBodyRenderer.tsx
  docs/
```

## 后续增强边界

- OCR/LLM 可以辅助把扫描件整理成 `question.*`、`answer.*` 和 `assets/*`，但结果必须可人工检查。
- 知识点库应从导入题目和人工标注中生长，不使用固定预设树作为生产真源。
- 比赛版使用 embedding API 生成向量，由项目在本地保存和检索；不把外部向量数据库设为运行依赖。
- 旧结构化数据库可以继续服务审核或兼容导入，但不能替代文件题库主模型。
- 私人 PDF、人工校对文本、数据库、API 密钥、参考压缩包和运行输出不得提交到 Git。
