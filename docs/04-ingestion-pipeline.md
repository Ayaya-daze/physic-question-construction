# 导入与识别管线

## 总体原则

导入的目标是生成可人工检查的文件题目，而不是强制生成复杂结构化数据库记录。

最终产物：

```text
questions/{question_id}/
  question.md | question.tex | question.txt
  answer.md   | answer.tex   | answer.txt
  assets/
  metadata.yaml
```

任何 OCR/LLM 结果都应先进入待审核状态，人工确认后才进入正式题库。

## 支持输入

- Markdown / LaTeX / TXT：可直接作为题目或答案文件。
- PDF / 图片：页面渲染后用多模态模型读取页面，OCR 只作为辅助提示，生成候选题文件和题图资产。
- Word / Excel / CSV / JSON：转换成题目文件；复杂字段可合并进正文或答案。

## 简单文件导入

最稳定的导入方式：

1. 上传 `question.md`。
2. 可选上传 `answer.md`。
3. 可选上传图片到 `assets/`。
4. 系统创建 `questions/{id}/`。
5. 用户在浏览器检查显示效果。
6. 重建索引。

## Agent Inbox 自动导入

为了减少人工操作，项目提供固定投放目录：

```text
imports/inbox/
```

人类把 PDF、扫描件、Markdown、LaTeX、TXT 或整理好的 `questions.json` 放入该目录。运行：

```bash
python3 skills/physics-question-importer/scripts/agent_inbox.py --project-root . run
```

脚本会把每个文件或文件夹转成标准 job：

```text
imports/jobs/{job_id}/
  source/
  output/
  manifest.json
  AGENT_TASK.md
```

如果 job 已经包含合法 `questions.json`，脚本会自动校验、写入 `questions/`、重建索引并归档到 `imports/done/`。

如果是 PDF/扫描件，agent 打开 `AGENT_TASK.md`，用 `physics-question-importer` skill 输出：

```text
imports/jobs/{job_id}/output/questions.json
imports/jobs/{job_id}/output/assets/*
```

再运行：

```bash
python3 skills/physics-question-importer/scripts/agent_inbox.py --project-root . finalize
```

即可自动完成校验、入库、索引重建和归档。

题目示例：

```markdown
# Work-energy theorem

A block of mass $m$ is pulled by force $F$ through displacement $s$.

![diagram](assets/diagram.png)

Find the final speed from rest.
```

答案示例：

```markdown
By the work-energy theorem,

$$
\frac12 m v^2 = Fs.
$$
```

## OCR 导入流程

```text
上传 PDF/图片
  -> 保存原始文件
  -> 页面渲染
  -> 多模态模型读页/切题
  -> 可选 OCR 识别作为辅助 hint
  -> 生成 question.* / answer.* / assets/*
  -> 人工审核
  -> 写入文件题库
  -> 重建索引
```

PDF/扫描件直导的验收规则：

- 扫描 PDF 的生产路径必须以页面图片为真源。CnOcr 文本只能作为辅助 hint。
- 对扫描件，text-only LLM 只能校对已经被 OCR 识别出来的文本，不能恢复 OCR 没读到的题号、公式、图或跨页边界。
- DeepSeek/text-only proofreading 不应作为扫描物理试卷的生产级导入路径；生产路径应接入 Claude/GPT-4o 等多模态模型直接读页。
- 如果没有 OCR/LLM 产生可靠 Markdown/LaTeX 题目文本，扫描 PDF 不应写入正式题库；整页渲染图只能作为识别/审核证据，不能作为 `question.md` 降级正文。
- PDF 文本抽取产生的 Unicode 数学符号、断行公式或乱码只能作为识别材料，不能直接作为生产题目正文。
- 如果 OCR/LLM 产生了可用文本，`question.md` 应保存 Markdown/LaTeX 文本；题图只应是独立图片或从 PDF 页面中裁剪出的题图资产，作为 `assets/*` 并在正文需要处引用。
- 原始 `source.pdf` 可以保留为资产或审计材料，但组卷导出不能靠拼接原始 PDF 代替题目文本渲染。

OCR 中间结果应保留：

- 原始文件路径。
- 页码。
- OCR 文本。
- 坐标和置信度。
- 裁剪图。
- 识别工具和版本。

已确认的 OCR/text-only 失败类型：

- OCR 读到了题号，但 text-only proofread 改写文本结构导致边界丢失。
- OCR 根本没读到页面上的题号，text-only LLM 无法从缺失文本中恢复。
- OCR 把页面噪声误读成题号，正则拆分会制造空题或误边界。

## LLM 辅助

LLM 可以做：

- 判断题目边界。
- 把 OCR 文本整理成可读 Markdown。
- 分离题目正文和答案正文。
- 提取图片引用说明。
- 建议 `metadata.yaml` 中的标题、来源、知识点、标签。
- 标记低置信度位置。
- 只按正文显式引用复制独立题图资产；`source_pages` 只是审计元数据，不能自动变成图片资产。
- 多模态模型应直接读取页面图片，校正 OCR 未读到或误读的题号、公式和图。

LLM 不应该：

- 擅自改写题意。
- 编造答案。
- 把题目强行塞进固定题型 schema。
- 未经人工确认直接入库。
- 把整份来源 PDF 的页面渲染图追加到任何题目正文，或按 `source_pages` 自动复制整页图进入 `assets/`。
- 依赖 text-only 模型声称恢复 OCR 根本没识别到的页面内容。

LLM 输出建议格式：

```json
{
  "question_body": "...",
  "answer_body": "...",
  "metadata": {
    "title": "...",
    "knowledge_points": ["..."],
    "source": "..."
  },
  "assets": [
    {"filename": "diagram.png", "source_region": [100, 200, 500, 380]}
  ],
  "warnings": ["答案疑似缺失"],
  "confidence": 0.82
}
```

## 人工审核工作台

审核界面应显示：

- 原始页面或截图。
- OCR 原文。
- 生成的题目正文。
- 生成的答案正文。
- 题图资产。
- 可选元数据。
- warnings 和置信度。

必要操作：

- 修改题目正文。
- 修改答案正文。
- 添加/删除图片。
- 合并/拆分候选题。
- 修改知识点标签。
- 批准写入文件题库。

## 错误处理

导入批次应报告：

- 原始文件无法读取。
- OCR 失败。
- LLM 输出无法解析。
- 图片资产缺失。
- 题目正文为空。
- 文件名冲突。

错误不应中断整个批次，除非原始文件无法读取。
