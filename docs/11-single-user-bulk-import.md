# 单用户大批量导入

日期：2026-07-02

## 目标

当前生产目标是一个操作者可以稳定导入大量资料，而不是公网多用户并发系统。

本轮采用轻量文件队列：

```text
POST /api/file-questions/import/jobs
  -> backend/uploads/file-import-jobs/{job_id}/manifest.json
  -> 后台单 worker 顺序处理
  -> questions/{id}/question.md
  -> questions/{id}/answer.md
  -> questions/{id}/assets/*
  -> 批量结束后重建一次 questions/.index/vector-index.json
```

## 浏览器工作流

1. 打开 `/upload`。
2. 一次选择多个 PDF、Markdown、LaTeX、Word、JSON 或图片文件。
3. 根据需要勾选 `LLM 辅助拆题`。
4. 点击 `提交后台导入任务`。
5. 页面显示 job id、进度、当前文件、已生成题目、错误和警告。
6. 任务完成后到 `/questions` 检查题目，再进入 `/papers/generator` 组卷。

浏览器请求只负责创建任务，不再等待所有文件解析完成。

## API

创建任务：

```http
POST /api/file-questions/import/jobs
Content-Type: multipart/form-data

files=<one or many files>
use_llm_assist=false
overwrite=false
```

查询任务：

```http
GET /api/file-questions/import/jobs/{job_id}
```

列出最近任务：

```http
GET /api/file-questions/import/jobs?limit=20
```

任务状态：

- `queued`：排队中。
- `running`：后台 worker 正在处理。
- `succeeded`：全部可处理文件成功。
- `partial`：至少入库了一部分题目，但有文件失败。
- `failed`：没有题目成功入库。

## 设计边界

- 后台 worker 单进程单线程，适合一个操作者的大批量任务。
- 生产运行后端时保持单进程/单 worker；不要用多个 Uvicorn worker 同时处理同一个文件队列。
- 每个任务按文件顺序处理，避免多个大 PDF 同时跑 OCR/LLM。
- 每个文件处理时不重建索引，任务结束后只重建一次。
- 后台非 JSON 导入会使用基于 job/file 的稳定题目 ID，降低服务中断后重复生成随机题目的风险。
- 任务 manifest 存在 `backend/uploads/file-import-jobs/{job_id}/manifest.json`。
- 服务重启时，`running` 任务会恢复成 `queued` 并重新处理。
- 已完成/失败的旧 job 可通过 `backend/scripts/cleanup_runtime_artifacts.py --delete` 清理。

## 仍然需要人工/agent 的地方

- 扫描 PDF 如果没有 vision-capable LLM，系统会失败并提示，而不是把整页图伪装成题目。
- 多模态识别出来的题目仍建议抽检，尤其是公式、题号、跨页题和题图。
- 题图必须是独立裁剪资产；整页 PDF 渲染图不能进入正式题目资产。

## 不覆盖的场景

- 多用户权限和隔离。
- 多 worker 并行导入。
- Web 端编辑/管理历史 job 的完整后台。
- 外部对象存储和外部向量数据库。

这些可以后续做，但不是当前单用户稳定导入的必要条件。
