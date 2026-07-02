# 组题与导出

## 目标

当前组卷模块做最小但真实可用的事情：

- 用户可以从题库中手动选择题目。
- 用户也可以输入相关知识点/搜索词和题目数，让系统从文件题库搜索补齐。
- LLM 辅助和语义搜索都是可选增强，不能替代题库选题。
- 输出题目卷 `questions.tex` / `questions.pdf`。
- 输出答案卷 `answers.tex` / `answers.pdf`。
- 如果题目文件引用图片，导出 PDF 必须包含对应图片。
- 题目和答案不能混在同一个 PDF 中作为最终交付物。

## 用户输入

浏览器组卷页 `/papers/generator` 支持：

- 试卷标题。
- 相关知识点或搜索词。
- 题目数。
- 可选 LLM/搜索辅助。
- 从题库列表中勾选题目。

手动选题是可选的。没有手动选题时，系统按搜索词和题目数从索引中选题。

## 验收目标接口

接口：

```http
POST /api/file-questions/papers/export
```

请求示例：

```json
{
  "title": "文件题库验收卷",
  "question_ids": ["sample-file-question"],
  "search_query": "work-energy theorem",
  "question_count": 1
}
```

响应包含：

```json
{
  "status": "succeeded",
  "export_id": "filepaper_...",
  "question_count": 1,
  "question_ids": ["sample-file-question"],
  "question_tex_url": "/api/file-questions/papers/exports/.../questions.tex",
  "question_pdf_url": "/api/file-questions/papers/exports/.../questions.pdf",
  "answer_tex_url": "/api/file-questions/papers/exports/.../answers.tex",
  "answer_pdf_url": "/api/file-questions/papers/exports/.../answers.pdf",
  "question_build_log_url": "/api/file-questions/papers/exports/.../build-questions.log",
  "answer_build_log_url": "/api/file-questions/papers/exports/.../build-answers.log"
}
```

导出目录：

```text
backend/exports/file-papers/{export_id}/
  questions.tex
  questions.pdf
  answers.tex
  answers.pdf
  build-questions.log
  build-answers.log
  assets/
    {question_id}/
      diagram.png
```

## 生成方式

生成器不理解复杂题型结构，只做文件拼接：

1. 读取每道题的 `question.*`。
2. 读取每道题的 `answer.*`；没有答案时在答案卷对应题号下写“未提供答案”。
3. Markdown/纯文本转换成简单 LaTeX。
4. LaTeX 正文基本原样放入模板，只重写相对图片路径。
5. 复制 `assets/` 到导出目录。
6. 用 `ctexart` 模板生成 `questions.tex`，内容只包含题目。
7. 用 `ctexart` 模板生成 `answers.tex`，内容只包含答案。
8. 调用 XeLaTeX 分别编译两个 PDF。
9. 分别保存编译日志。

Markdown 图片：

```markdown
![block force diagram](assets/diagram.png)
```

导出时转为：

```tex
\begin{center}
\includegraphics[width=0.65\linewidth,height=0.26\textheight,keepaspectratio]{sample-file-question/diagram.png}
\par\small{block force diagram}
\end{center}
```

模板里设置：

```tex
\graphicspath{{assets/}}
```

因此 PDF 编译时会读取导出目录中的资产副本。

如果 `question.md` 是 OCR/LLM 生成的 Markdown/LaTeX 文本，组卷必须把这些文本写入 `questions.tex`。扫描 PDF 的整页渲染图不能作为题目正文降级进入 TeX；只有独立题图或从页面裁剪出的题图资产才可通过 `\includegraphics` 写入。导出不能通过合并原始 PDF 来代替 TeX 生成。

## 验收标准

当前可交付版本至少满足：

- `/questions` 能列出文件题库。
- `/questions/{id}` 能显示题目正文、答案、图片和 LaTeX 公式。
- `/api/file-questions/reindex` 能从文件题库重建索引。
- `/papers/generator` 能选择题目或按搜索词自动选题。
- 导出后能下载 `questions.tex` 和 `answers.tex`。
- 本地有 XeLaTeX 时能生成 `questions.pdf` 和 `answers.pdf`。
- 题目 PDF 不包含答案区。
- 答案 PDF 不混入完整题目正文，最多保留题号和必要引用。
- 含图题的题目 PDF 中能看到题图；答案中引用图片时答案 PDF 也能看到对应图片。
- 编译失败时仍保留对应 TeX 和日志。

## 后续增强

后续可以增加：

- 更好的 Markdown 转 TeX。
- 自定义模板。
- 更强的语义搜索或外部向量库。
- LLM 只做需求解析、候选解释和替换建议。

不建议把题目核心重新拆成固定的题型、选项、答案类型、解析步骤。那些结构对生产题库的覆盖面太窄，应该作为兼容或可选导入视图，而不是主模型。
