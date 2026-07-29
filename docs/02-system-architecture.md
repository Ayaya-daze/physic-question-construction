# 系统架构

## 当前架构

```text
浏览器
  -> Next.js 前端
  -> FastAPI 后端
    -> questions/ 文件题库
    -> questions/.index/ FTS5、向量和动态知识点
    -> uploads/ 文件任务与审核候选
    -> exports/file-papers/
    -> SQLite 旧结构兼容层
```

当前主路径：

1. 文件题库保存题目正文、答案正文和资产。
2. 后端直接读取题目文件。
3. 索引从文件重建。
4. 前端展示文件内容，渲染公式和图片。
5. 组卷服务拼接题目文件，分别生成题目卷和答案卷 TeX/PDF。

数据库存在，但不是题目正文真源。

## 推荐技术栈

| 层 | 当前选择 | 说明 |
| --- | --- | --- |
| 后端 | Python + FastAPI | 文件读取、索引、导出、OCR/LLM 扩展方便 |
| 前端 | Next.js + TypeScript | 浏览器操作界面 |
| 文件存储 | 本地 `questions/` | 当前题库真源 |
| 当前索引 | SQLite FTS5 + 本地 float32 向量 | 可选 embedding API，检索和融合由项目实现 |
| PDF | XeLaTeX | 生成 TeX/PDF 试卷 |
| 数据库 | SQLite | 旧结构兼容层；不是题目正文真源 |

## 模块划分

### 1. 文件题库服务

职责：

- 读取 `question.*` 和 `answer.*`。
- 枚举 `assets/`。
- 读取可选 `metadata.yaml`。
- 创建和上传题目文件。
- 校验 `question_id` 和资产路径安全。

### 2. 展示服务

职责：

- 前端列表和详情页。
- Markdown/文本显示。
- LaTeX 数学公式渲染。
- 图片资产展示。

### 3. 索引与搜索服务

职责：

- 从题目文件重建索引。
- 保存 `content_hash`。
- 搜索题目正文、答案和元数据。
- 使用 FTS5、可选 embedding API、本地余弦检索和 RRF 融合。
- embedding API 不可用时保留本地降级索引。

### 4. 组卷与导出服务

职责：

- 接收选题、搜索词和题目数。
- 从题库读取题目和答案。
- 把 Markdown/文本转换成简单 TeX；LaTeX 原文基本保留。
- 复制图片资产。
- 写出 `questions.tex` 和 `answers.tex`。
- 分别编译 `questions.pdf` 和 `answers.pdf`。
- 提供题目卷、答案卷和各自编译日志的下载链接。
- 输出含题目顺序、内容哈希、来源哈希、资产哈希和编译状态的 `manifest.json`。

验收底线：不能只生成一个包含题目和答案的混合 PDF。答案必须进入独立答案卷。

### 5. 导入增强服务

职责：

- 上传原始 PDF、图片、Word、Markdown、LaTeX 等。
- 当前可由解析器、视觉 API 或 Codex Skill 生成待审核候选。
- 高风险候选必须经编辑、warning 确认和批准后才能进入正式题库。
- 审核通过后使用 staging 和原子重命名提交正式题库。
- 比赛下一阶段自行完成页级证据块、缓存、答案匹配和局部题图裁剪。

## 数据流

### 文件题库读取

```text
questions/{id}/question.*
questions/{id}/answer.*
questions/{id}/assets/*
  -> FastAPI file-questions API
  -> Next.js 页面渲染
```

### 索引

```text
题目文件
  -> 提取标题、正文、答案、metadata
  -> SQLite FTS5/BM25
  -> embedding API 或本地降级向量
  -> vectors.f32 + vector-map.json + index-manifest.json
  -> 动态 knowledge-points.json
```

### 组卷导出

```text
用户选题/搜索词/题目数
  -> 解析题目 ID
  -> 读取 question.* 和 answer.*
  -> 复制 assets
  -> question.* 拼入题目卷 LaTeX 模板
  -> answer.* 拼入答案卷 LaTeX 模板
  -> xelatex 分别编译
  -> questions.tex + questions.pdf
  -> answers.tex + answers.pdf
  -> build-questions.log + build-answers.log
```

## 端口与访问方式

本地默认：

| 服务 | 默认地址 |
| --- | --- |
| 前端 Web | `http://localhost:3000` 或生产预览 `http://localhost:3001` |
| 后端 API | `http://localhost:8000` |
| API 文档 | `http://localhost:8000/docs` |

本机使用时只绑定 `127.0.0.1`。如果要从局域网、Tailscale 或另一台设备访问，再绑定 `0.0.0.0`，并补登录鉴权。

## 后续扩展

- 增加页级视觉 API 队列、缓存、任务恢复和调用量统计。
- 增加来源区域对照、候选拆分合并和局部题图裁剪。
- 增加动态知识点确认、删除和检索质量评测。
- 增加模板管理。
- 增加用户权限和操作日志。

比赛主链路不依赖完整第三方 OCR 平台、外部向量数据库或 Codex Agent。扩展时仍保持一条底线：题目正文和答案正文落在文件中，复杂结构只能作为可重建的视图或兼容层。
