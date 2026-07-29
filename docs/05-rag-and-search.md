# RAG 与向量检索

## 目标

RAG 层服务于题库搜索和组卷候选召回，不替代文件题库。

主要能力：

- 关键词检索。
- 语义检索。
- 相似题推荐。
- 重复题提示。
- 根据自然语言需求找候选题。

## 基本原则

1. 文件题库是真源。
2. 向量库只是可重建索引。
3. 索引项必须记录 `question_id` 和 `content_hash`。
4. 搜索结果必须能回到原题文件。
5. LLM 只能基于检索到的题库题目做解释或建议。

## 当前实现

当前索引全部保存在本地并可从题目文件重建：

```text
questions/.index/
  lexical.sqlite
  vectors.f32
  vector-map.json
  index-manifest.json
  vector-index.json
```

索引文本来自：

- `title`
- `question_body`
- `answer_body`
- `metadata.yaml`

接口：

```http
POST /api/file-questions/reindex
GET  /api/file-questions?q=...
```

默认关闭外部 API，使用明确标记为 fallback 的本地 hash 向量配合 FTS5。配置 OpenAI-compatible embedding API 后，索引会保存真实 dense vector；API 建索引失败时自动降级并把错误写入 `index-manifest.json`，查询时 API 暂时不可用也不会影响关键词召回。

## 检索流程

```text
用户搜索词/知识点
  -> FTS5/BM25 关键词召回
  -> 本地向量余弦召回
  -> RRF 融合
  -> 读取题目文件
  -> 返回题目 ID、标题、预览、资产数、索引状态
```

组卷时：

```text
用户输入 search_query + question_count
  -> search_questions
  -> 选出题目 ID
  -> 读取 question.* / answer.*
  -> 分别导出题目卷和答案卷 TeX/PDF
```

## 当前比赛基线

当前已经实现：

- SQLite FTS5/BM25 负责精确关键词召回。
- 可替换 embedding API 生成真实 dense vector。
- 本地 `vectors.f32` 与 `vector-map.json` 保存向量和题目映射。
- 项目内实现余弦检索和 Reciprocal Rank Fusion。
- 动态知识点作为列表与组卷前的 metadata 筛选条件。

比赛部署不依赖 pgvector、Qdrant 等外部向量数据库。所有索引仍能从题目文件重建。

后续工作：

- 建立查询真值集并测量 Recall@10、nDCG@10 和 P95。
- 在搜索接口中增加通用 metadata filter。
- 评估只处理少量候选的可选 reranker。

## 相似题与重复题

相似题判断可以考虑：

- 题目正文向量相似度。
- 答案正文相似度。
- 公式相似度。
- 图片说明或 OCR caption。
- 来源信息。

这些都应该作为提示或候选，不自动删除或合并题目。

## 质量评估

需要小型评测集：

- 查询语句。
- 期望召回题目。
- 不应召回题目。
- 相似题标注。

指标：

- Recall@10。
- nDCG@10。
- 查询 P95 延迟。
- 重复题误判率。
- 组卷候选可用率。
