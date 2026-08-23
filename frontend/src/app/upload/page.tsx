'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertCircle, Bot, Check, FileText, Loader2, X } from 'lucide-react';
import FileUploader from '@/components/FileUploader';
import QuestionBodyRenderer from '@/components/QuestionBodyRenderer';
import type { FileImportConfig, FileImportJob, FileQuestionCandidate } from '@/lib/api';
import {
  approveFileQuestionCandidate,
  createFileImportJob,
  getFileImportConfig,
  getFileImportJob,
  listFileImportJobs,
  listFileQuestionCandidates,
  rejectFileQuestionCandidate,
} from '@/lib/api';

const doneStatuses = new Set(['succeeded', 'partial', 'failed', 'needs_review']);
const activeStatuses = new Set(['queued', 'running']);
const lastJobStorageKey = 'physics-qb:last-file-import-job-id';

const statusLabels: Record<string, string> = {
  draft: '准备中',
  queued: '排队中',
  running: '处理中',
  succeeded: '已完成',
  partial: '部分完成',
  needs_review: '等待审核',
  failed: '失败',
};

function JobStatusPanel({ job, onRefresh }: { job: FileImportJob; onRefresh: () => void }) {
  const progress = job.total_files > 0 ? Math.round((job.processed_files / job.total_files) * 100) : 0;
  const active = !doneStatuses.has(job.status);

  return (
    <section className="rounded-lg border border-blue-200 bg-blue-50 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            {active && <Loader2 className="h-4 w-4 animate-spin text-blue-600" />}
            <h2 className="text-sm font-semibold text-blue-950">
              后台导入任务：{statusLabels[job.status] || job.status}
            </h2>
          </div>
          <p className="mt-1 font-mono text-xs text-blue-800">{job.job_id}</p>
        </div>
        <button
          onClick={onRefresh}
          className="rounded-lg bg-white px-3 py-1.5 text-xs font-medium text-blue-700 ring-1 ring-blue-200 hover:bg-blue-100"
        >
          刷新状态
        </button>
      </div>

      <div className="mt-4">
        <div className="flex items-center justify-between text-xs text-blue-900">
          <span>{job.processed_files} / {job.total_files} 个文件</span>
          <span>{progress}%</span>
        </div>
        <div className="mt-1 h-2 rounded-full bg-white">
          <div className="h-2 rounded-full bg-blue-600 transition-all" style={{ width: `${progress}%` }} />
        </div>
      </div>

      {job.current_file && (
        <p className="mt-3 text-sm text-blue-900">当前文件：{job.current_file}</p>
      )}

      <div className="mt-4 grid gap-3 sm:grid-cols-4">
        <div className="rounded-lg bg-white p-3 ring-1 ring-blue-100">
          <p className="text-xs text-blue-600">已入库题目</p>
          <p className="mt-1 text-lg font-semibold text-blue-950">{job.imported_count}</p>
        </div>
        <div className="rounded-lg bg-white p-3 ring-1 ring-blue-100">
          <p className="text-xs text-blue-600">待审核</p>
          <p className="mt-1 text-lg font-semibold text-blue-950">{job.review_count}</p>
        </div>
        <div className="rounded-lg bg-white p-3 ring-1 ring-blue-100">
          <p className="text-xs text-blue-600">错误</p>
          <p className="mt-1 text-lg font-semibold text-blue-950">{job.errors.length}</p>
        </div>
        <div className="rounded-lg bg-white p-3 ring-1 ring-blue-100">
          <p className="text-xs text-blue-600">索引</p>
          <p className="mt-1 text-sm font-medium text-blue-950">{job.index_rebuilt ? '已重建' : '等待完成'}</p>
        </div>
      </div>

      {job.created_question_ids.length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-semibold text-blue-900">已生成题目</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {job.created_question_ids.map((questionId) => (
              <Link
                key={questionId}
                href={`/questions/files/${questionId}`}
                target="_blank"
                className="rounded-full bg-white px-3 py-1.5 font-mono text-xs text-blue-700 ring-1 ring-blue-200 hover:bg-blue-100"
              >
                {questionId}
              </Link>
            ))}
          </div>
        </div>
      )}

      {job.errors.length > 0 && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3">
          <p className="text-xs font-semibold text-red-800">错误</p>
          <ul className="mt-2 space-y-1">
            {job.errors.map((err, index) => (
              <li key={index} className="text-xs text-red-700">
                {err.filename || '任务'}：{err.error}
              </li>
            ))}
          </ul>
        </div>
      )}

      {job.warnings.length > 0 && (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3">
          <p className="text-xs font-semibold text-amber-900">警告</p>
          <ul className="mt-2 space-y-1">
            {job.warnings.slice(-8).map((warning, index) => (
              <li key={index} className="text-xs text-amber-800">{warning}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function CandidateReview({
  candidate,
  onResolved,
}: {
  candidate: FileQuestionCandidate;
  onResolved: () => Promise<void>;
}) {
  const [questionBody, setQuestionBody] = useState(candidate.question_body);
  const [answerBody, setAnswerBody] = useState(candidate.answer_body);
  const [acknowledgeWarnings, setAcknowledgeWarnings] = useState(candidate.warnings.length === 0);
  const [working, setWorking] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const assetBaseUrl = `/api/file-questions/import/candidates/${candidate.candidate_id}/assets`;

  const approve = async () => {
    setWorking(true);
    setActionError(null);
    try {
      await approveFileQuestionCandidate(candidate.candidate_id, {
        question_body: questionBody,
        answer_body: answerBody,
        acknowledge_warnings: acknowledgeWarnings,
      });
      await onResolved();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '批准失败');
    } finally {
      setWorking(false);
    }
  };

  const reject = async () => {
    setWorking(true);
    setActionError(null);
    try {
      await rejectFileQuestionCandidate(candidate.candidate_id);
      await onResolved();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '驳回失败');
    } finally {
      setWorking(false);
    }
  };

  return (
    <article className="border-t border-gray-200 py-6 first:border-t-0 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-gray-900">
            {String(candidate.metadata.title || candidate.source_filename)}
          </p>
          <p className="mt-1 text-xs text-gray-500">
            {candidate.source_filename} · <span className="font-mono">{candidate.proposed_question_id}</span>
          </p>
        </div>
        <span className="rounded bg-amber-100 px-2 py-1 text-xs font-medium text-amber-800">
          待审核
        </span>
      </div>

      {candidate.warnings.length > 0 && (
        <div className="mt-4 border-l-2 border-amber-400 pl-3">
          {candidate.warnings.map((warning) => (
            <p key={warning} className="text-xs text-amber-800">{warning}</p>
          ))}
        </div>
      )}

      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <div className="space-y-4">
          <label className="block">
            <span className="text-xs font-semibold text-gray-700">题目正文</span>
            <textarea
              value={questionBody}
              onChange={(event) => setQuestionBody(event.target.value)}
              className="mt-2 min-h-56 w-full resize-y rounded border border-gray-300 p-3 font-mono text-sm leading-6 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-gray-700">答案正文</span>
            <textarea
              value={answerBody}
              onChange={(event) => setAnswerBody(event.target.value)}
              className="mt-2 min-h-36 w-full resize-y rounded border border-gray-300 p-3 font-mono text-sm leading-6 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          </label>
        </div>

        <div className="space-y-5">
          <div>
            <p className="mb-2 text-xs font-semibold text-gray-700">题目预览</p>
            <div className="min-h-56 border-l border-gray-200 pl-4">
              <QuestionBodyRenderer
                body={questionBody}
                format={candidate.question_format}
                questionId={candidate.candidate_id}
                assetBaseUrl={assetBaseUrl}
              />
            </div>
          </div>
          {answerBody.trim() && (
            <div>
              <p className="mb-2 text-xs font-semibold text-gray-700">答案预览</p>
              <div className="border-l border-gray-200 pl-4">
                <QuestionBodyRenderer
                  body={answerBody}
                  format={candidate.answer_format || candidate.question_format}
                  questionId={candidate.candidate_id}
                  assetBaseUrl={assetBaseUrl}
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {candidate.warnings.length > 0 && (
        <label className="mt-5 flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={acknowledgeWarnings}
            onChange={(event) => setAcknowledgeWarnings(event.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          已对照来源并处理以上警告
        </label>
      )}

      {actionError && <p className="mt-3 text-sm text-red-700">{actionError}</p>}

      <div className="mt-5 flex flex-wrap justify-end gap-2">
        <button
          type="button"
          onClick={reject}
          disabled={working}
          className="inline-flex items-center gap-2 rounded border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          <X className="h-4 w-4" />
          驳回
        </button>
        <button
          type="button"
          onClick={approve}
          disabled={working || !questionBody.trim() || !acknowledgeWarnings}
          className="inline-flex items-center gap-2 rounded bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {working ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
          批准入库
        </button>
      </div>
    </article>
  );
}

export default function UploadPage() {
  const [uploading, setUploading] = useState(false);
  const [useLlmAssist, setUseLlmAssist] = useState(false);
  const [llmConfig, setLlmConfig] = useState<FileImportConfig | null>(null);
  const [job, setJob] = useState<FileImportJob | null>(null);
  const [candidates, setCandidates] = useState<FileQuestionCandidate[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refreshCandidates = async () => {
    setCandidates(await listFileQuestionCandidates('needs_review', 200));
  };

  useEffect(() => {
    getFileImportConfig()
      .then(setLlmConfig)
      .catch(() => setLlmConfig(null));
  }, []);

  useEffect(() => {
    refreshCandidates().catch(() => setCandidates([]));
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function restoreJob() {
      let savedJob: FileImportJob | null = null;
      try {
        const savedJobId = window.localStorage.getItem(lastJobStorageKey);
        if (savedJobId) {
          savedJob = await getFileImportJob(savedJobId);
        }
      } catch {
        window.localStorage.removeItem(lastJobStorageKey);
      }

      try {
        const recentJobs = await listFileImportJobs(10);
        const activeJob = recentJobs.find((item) => activeStatuses.has(item.status));
        const restoredJob = activeJob || recentJobs[0] || savedJob;
        if (!cancelled && restoredJob) {
          setJob(restoredJob);
          window.localStorage.setItem(lastJobStorageKey, restoredJob.job_id);
        }
      } catch {
        if (!cancelled && savedJob) setJob(savedJob);
      }
    }

    restoreJob();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!job || doneStatuses.has(job.status)) return;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const fresh = await getFileImportJob(job.job_id);
        if (!cancelled) {
          setJob(fresh);
          if (fresh.status === 'needs_review') {
            refreshCandidates().catch(() => undefined);
          }
        }
      } catch {
        // Keep the last known state; manual refresh can retry.
      }
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [job?.job_id, job?.status]);

  const refreshJob = async () => {
    if (!job) return;
    setJob(await getFileImportJob(job.job_id));
    await refreshCandidates();
  };

  const handleUpload = async (files: File[]) => {
    setUploading(true);
    setError(null);

    try {
      const created = await createFileImportJob(files, { use_llm_assist: useLlmAssist });
      window.localStorage.setItem(lastJobStorageKey, created.job_id);
      setJob(created);
      await refreshCandidates();
    } catch (err) {
      setError(err instanceof Error ? err.message : '导入失败');
    } finally {
      setUploading(false);
    }
  };

  const llmUnavailable = !llmConfig?.configured;
  const visionUnavailable = Boolean(llmConfig?.configured && !llmConfig?.vision_configured);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">导入题目文件</h1>
        <p className="mt-1 text-sm text-gray-500">
          上传 PDF、Markdown、Word、LaTeX、结构化 JSON 或图片；高风险识别结果先进入审核区
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      <section className="rounded-lg border border-gray-200 bg-white p-4">
        <label className={`flex items-start gap-3 ${llmUnavailable ? 'opacity-70' : ''}`}>
          <input
            type="checkbox"
            checked={useLlmAssist}
            disabled={llmUnavailable || uploading}
            onChange={(event) => setUseLlmAssist(event.target.checked)}
            className="mt-1 h-4 w-4 rounded border-gray-300 text-gray-900 focus:ring-gray-900"
          />
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-gray-900">
              <Bot className="h-4 w-4" />
              LLM 辅助拆题
            </div>
            <p className="mt-1 text-sm text-gray-500">
              未勾选时，Markdown/LaTeX/文本文件会保守导入为一个题目文件；扫描 PDF 需要可读页面的多模态模型生成 Markdown/LaTeX 题目文本。
            </p>
            {llmUnavailable && (
              <p className="mt-2 inline-flex items-center gap-1 text-xs text-amber-700">
                <AlertCircle className="h-3.5 w-3.5" />
                后端未配置 LLM_ENABLED=true 和 LLM_API_KEY，当前不能开启。
              </p>
            )}
            {visionUnavailable && (
              <p className="mt-2 inline-flex items-center gap-1 text-xs text-amber-700">
                <AlertCircle className="h-3.5 w-3.5" />
                当前模型不支持读图，扫描 PDF/图片不能自动拆题，只能处理已有文本的文件。
              </p>
            )}
            {llmConfig?.configured && (
              <p className="mt-2 text-xs text-gray-400">
                当前模型：{llmConfig.provider} / {llmConfig.model} · {llmConfig.vision_configured ? '支持读图' : '不支持读图'}
              </p>
            )}
          </div>
        </label>
      </section>

      <FileUploader onUpload={handleUpload} uploading={uploading} />

      {job && <JobStatusPanel job={job} onRefresh={refreshJob} />}

      {candidates.length > 0 && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-5">
            <h2 className="text-base font-semibold text-gray-900">待审核题目</h2>
            <p className="mt-1 text-sm text-gray-500">
              对照来源修正正文和答案，确认警告后才会写入正式题库。
            </p>
          </div>
          {candidates.map((candidate) => (
            <CandidateReview
              key={candidate.candidate_id}
              candidate={candidate}
              onResolved={async () => {
                await refreshCandidates();
                if (job) setJob(await getFileImportJob(job.job_id));
              }}
            />
          ))}
        </section>
      )}

      <div className="rounded-lg border border-gray-200 bg-gray-50 p-5">
        <h3 className="text-sm font-semibold text-gray-700">支持的格式</h3>
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-5">
          {[
            { icon: '📄', label: 'PDF', desc: '文本层或审核候选' },
            { icon: '📝', label: 'Markdown', desc: '原文入库' },
            { icon: '📃', label: 'Word', desc: '.docx' },
            { icon: '{}', label: 'JSON', desc: '题目/答案/资产' },
            { icon: '📐', label: 'LaTeX', desc: '原文入库' },
            { icon: '🖼️', label: '图片', desc: '生成审核候选' },
          ].map((fmt) => (
            <div
              key={fmt.label}
              className="rounded-lg border border-gray-200 bg-white p-3 text-center"
            >
              <p className="text-2xl">{fmt.icon}</p>
              <p className="mt-1 text-xs font-medium text-gray-700">{fmt.label}</p>
              <p className="text-xs text-gray-400">{fmt.desc}</p>
            </div>
          ))}
        </div>
        <div className="mt-4 flex items-center gap-2 text-xs text-gray-500">
          <FileText className="h-3.5 w-3.5" />
          导入后的题目存储为 question.md / answer.md / assets，并可在题库页搜索与组卷。
        </div>
      </div>
    </div>
  );
}
