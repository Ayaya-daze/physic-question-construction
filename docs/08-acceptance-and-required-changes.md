# 验收报告与剩余风险

日期：2026-07-02

补充验收：2026-07-27

## 当前结论

文件题库主路径已经达到 MVP 可交付口径：题目以 `question.*` / `answer.*` / `assets/*` / `metadata.yaml` 存储；本地索引可重建；组卷按题目文本生成 TeX，并分别输出题目卷和答案卷 PDF。

旧结构化数据库、选择题选项、解析步骤等仍在仓库中作为兼容层，不是当前生产题库真源。

本轮维护后，生产部署路径也补齐了必要底座：默认关闭 DEBUG、题库目录可配置、Docker 使用生产启动方式、题库/导出/上传目录使用持久卷、前端 API 代理可通过环境变量指定后端、文件组卷 LaTeX 编译进入受控线程池并限制并发。

再次整理后，默认前端入口也已切到文件题库：侧边栏不再暴露旧审核/知识点入口，`/questions` 是文件题库列表，`/papers` 会跳转到 `/papers/generator`。

单用户大批量导入已改成后台任务：`/upload` 提交 job 后立即返回，后端单 worker 顺序处理，任务结束后统一重建索引。

## 已通过项

- 题库核心只依赖题目正文、答案正文、资产和松散元数据。
- 前端按 Markdown/LaTeX 渲染文件题目。
- 首页和题库页读取文件题库数据，而不是旧结构化数据库。
- `/api/file-questions/import/jobs` 支持后台批量导入任务和状态查询。
- 向量索引从文件重建，用于搜索和组卷候选召回。
- `POST /api/file-questions/papers/export` 输出 `questions.tex/pdf` 与 `answers.tex/pdf`。
- 导出会复制独立题图资产，并跳过整页 PDF 渲染图。
- 扫描 PDF 没有可靠视觉/人工识别时，不应把整页图片伪装成题目资产。
- 本地 `.env` 不应保存真实 API key；生产密钥通过环境变量注入。
- Docker Compose 使用持久卷保存 `/data/questions`、`/data/exports`、`/data/uploads`。
- 前端生产服务通过 `BACKEND_URL` 代理 `/api/*`，容器内不再写死 `127.0.0.1:8000`。
- 文件题库导出编译受 `FILE_EXPORT_MAX_WORKERS` 和 `LATEX_COMPILE_TIMEOUT_SECONDS` 控制，避免并发 XeLaTeX 把服务拖死。
- 提供 `backend/scripts/cleanup_runtime_artifacts.py` 清理旧导出和旧导入临时文件，默认 dry-run。
- 文件题目写入和 Skill materializer 已增加全量预检、稳定 ID、原子目录提交、冲突停止和中断恢复。
- 视觉/LLM、PDF、图片和显式高风险 JSON 只生成待审核候选，不能自动越过审核闸门。
- 知识点页面从正式题目 metadata 动态生成，支持改名、合并和直接筛题。
- 当前索引已使用 SQLite FTS5、本地 float32 向量和 RRF，可选接入真实 embedding API。
- 文件组卷新增 `manifest.json` 和最可能编译失败题目 ID。
- 13 项文件主链路回归测试、前端构建和浏览器端到端冒烟通过。

## 剩余风险

- 扫描卷生产导入仍依赖多模态模型或人工校对；CnOcr + text-only LLM 只能做草稿。
- 已重建的样例题需要人审文本和公式准确性，尤其是图片占位和跨页题。
- 旧结构化 API 还在代码中，维护时必须避免把主路径改回硬编码题型 schema。
- 真实 embedding API 已有可选接口，但尚无脱敏检索真值集，不能声称语义召回指标已达标。
- 页级证据块、选择性视觉调用、题答自动配对和局部题图裁剪尚未完成，仍是扫描资料规模化导入的主要风险。
- 当前没有用户认证和权限控制，不适合直接暴露在公网；生产应放在内网/VPN 或加反向代理认证。
- Docker 后端镜像包含 XeLaTeX/CJK，镜像较大；这是为了保证容器内 PDF 导出真实可用。
- 如果本地曾经保存过真实 LLM key，应在服务商后台轮换。

## 回归验收清单

- 导入 Markdown/LaTeX 题目，详情页能渲染正文、答案和公式。
- 导入扫描 PDF，不开 vision LLM 时给出明确失败/需人工识别提示。
- 开启 vision LLM 时输出仍是简单 `question_body`、`answer_body`、`metadata`。
- 含图题组卷后，`questions.tex` 引用复制后的独立图片资产。
- `questions.pdf` 只有题目，`answers.pdf` 只有答案或“未提供答案”。
