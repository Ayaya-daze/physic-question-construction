# 文档索引

本文给出当前仓库文档的阅读顺序和效力层级，避免早期设计、历史验收和比赛目标互相覆盖。

## 当前入口

| 文档 | 用途 | 状态 |
| --- | --- | --- |
| [../README.md](../README.md) | 当前可运行能力、启动方式和接口入口 | 当前 |
| [14-competition-project-plan.md](14-competition-project-plan.md) | 比赛版本目标、边界、架构、指标和演示 | 目标方案 |
| [07-implementation-plan.md](07-implementation-plan.md) | 从当前基线推进到比赛版本的执行清单 | 当前路线 |
| [12-first-delivery-test.md](12-first-delivery-test.md) | 第一版交付基线与用户测试方法 | 已完成基线 |
| [13-reference-project-review.md](13-reference-project-review.md) | 三套参考项目的审查、验证与采用决策 | 研究结论 |

## 产品与架构

| 文档 | 内容 |
| --- | --- |
| [01-product-requirements.md](01-product-requirements.md) | 产品需求与使用场景 |
| [02-system-architecture.md](02-system-architecture.md) | 系统分层与组件关系 |
| [03-data-model.md](03-data-model.md) | 数据模型；文件题库口径优先于旧兼容模型 |
| [04-ingestion-pipeline.md](04-ingestion-pipeline.md) | 资料导入流程 |
| [05-rag-and-search.md](05-rag-and-search.md) | 检索与 RAG 设计 |
| [06-paper-generation.md](06-paper-generation.md) | TeX/PDF 组卷与输出 |

## 运维与验收

| 文档 | 内容 |
| --- | --- |
| [08-acceptance-and-required-changes.md](08-acceptance-and-required-changes.md) | 早期验收问题和修订要求 |
| [09-agent-inbox-workflow.md](09-agent-inbox-workflow.md) | Codex Skill/Agent Inbox 维护流程 |
| [10-project-review-and-organization.md](10-project-review-and-organization.md) | 2026-07-02 的历史整理快照 |
| [11-single-user-bulk-import.md](11-single-user-bulk-import.md) | 单用户批量导入运行方式 |
| [skill-interface.md](skill-interface.md) | Skill 输出接口约定 |

## 效力规则

1. 正式题库始终以 `questions/{id}/question.*`、`answer.*` 和局部资产为真源。
2. 比赛目标以 `14-competition-project-plan.md` 为准。
3. 当前开发优先级以 `07-implementation-plan.md` 为准。
4. 历史记录中的路径、样题名称和当时结论不自动成为当前运行要求。
5. 参考项目只提供设计证据，未经安全和端到端验证的代码不直接合并。
