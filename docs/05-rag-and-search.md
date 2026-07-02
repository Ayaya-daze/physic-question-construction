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

## 当前 MVP

当前本地索引：

```text
questions/.index/vector-index.json
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

当前向量实现是本地 hash 向量，适合 MVP 验证流程；后续可替换为真实 embedding 模型。

## 检索流程

```text
用户搜索词/知识点
  -> 本地索引召回
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

## 后续增强

可以引入：

- OpenAI / 本地 embedding 模型。
- pgvector。
- Qdrant。
- BM25 + vector hybrid search。
- rerank 模型。

但外部向量库仍只保存索引，不保存题目真源。

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

- recall@k。
- precision@k。
- 重复题误判率。
- 组卷候选可用率。
