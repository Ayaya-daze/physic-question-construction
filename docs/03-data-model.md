# 数据模型

## 当前主模型：文件题库

生产可用的最小模型只要求每道题有题目文件、答案文件、资产目录和可重建索引。

```text
questions/{question_id}/
  question.md | question.tex | question.txt
  answer.md   | answer.tex   | answer.txt
  assets/
    *.png | *.jpg | *.svg | *.pdf | ...
  metadata.yaml  # 可选
```

核心原则：

- 文件系统是题库真源。
- 向量库是索引，可以随时从文件重建。
- 数据库只做兼容、审核、历史记录或扩展能力，不是当前题目正文真源。
- 题目内部不硬编码选择题、选项、解析步骤、多小问等结构。
- 题目正文和答案正文可以写 Markdown、LaTeX 或纯文本；显示端负责渲染数学公式和图片。
- `metadata.yaml` 是松散附属信息，可以记录标题、来源、知识点、标签等，但不要求固定 schema。

## 文件字段

### question.*

题目正文。可以包含：

- 普通文本。
- Markdown 段落、标题、列表。
- LaTeX 数学公式，例如 `$F=ma$`、`$$E_k=\frac12mv^2$$`。
- 图片引用，例如 `![diagram](assets/diagram.png)`。
- 如果题目本身是选择题，选项直接写在正文里。

### answer.*

答案正文。可以包含：

- 最终答案。
- 必要推导。
- 解析说明。
- 图片或公式。

系统不拆分“答案”和“解析步骤”。需要详细解析时直接写在答案文件里。

### assets/

题图、扫描裁剪图、表格图、公式图等。题目正文和答案正文通过相对路径引用。

### metadata.yaml

可选，例如：

```yaml
title: Work-energy theorem with a diagram
knowledge_points:
  - work-energy theorem
  - force and displacement
source: local acceptance sample
```

这些字段只用于检索、展示和人工管理，不决定题目结构。

## 向量索引

当前本地索引文件：

```text
questions/.index/vector-index.json
```

索引内容来自：

- 标题。
- 题目正文。
- 答案正文。
- 可选 metadata。

索引项必须保存：

- `question_id`
- `content_hash`
- `updated_at`
- `vector`

如果题目文件变化，索引状态会变为“需重建”。重建索引不会改写题目正文。

## 兼容层

仓库中仍有旧的结构化模型，例如 `Question`、`ChoiceOption`、`Answer`、`SolutionStep`、`Paper` 等。这些可以继续用于历史数据、导入实验或审核流程，但当前产品主路径不依赖它们。

判断一项新功能是否应该进入主模型：

- 如果没有它，题目是否仍能存储、显示、搜索、导出？
- 如果题目类型变化，它是否会限制题目表达？
- 它是否能从文件内容重建？

不能重建、会限制题目表达、或只是为了“看起来结构化”的字段，不进入题库核心。
