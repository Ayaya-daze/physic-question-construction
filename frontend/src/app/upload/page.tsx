'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertCircle, Bot, FileText, Loader2 } from 'lucide-react';
import FileUploader from '@/components/FileUploader';
import type { FileImportConfig, FileImportJob } from '@/lib/api';
import { createFileImportJob, getFileImportConfig, getFileImportJob, listFileImportJobs } from '@/lib/api';

const doneStatuses = new Set(['succeeded', 'partial', 'failed']);
const activeStatuses = new Set(['queued', 'running']);
const lastJobStorageKey = 'physics-qb:last-file-import-job-id';

const statusLabels: Record<string, string> = {
  draft: '准备中',
  queued: '排队中',
  running: '处理中',
  succeeded: '已完成',
  partial: '部分完成',
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

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg bg-white p-3 ring-1 ring-blue-100">
          <p className="text-xs text-blue-600">已入库题目</p>
          <p className="mt-1 text-lg font-semibold text-blue-950">{job.imported_count}</p>
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

export default function UploadPage() {
  const [uploading, setUploading] = useState(false);
  const [useLlmAssist, setUseLlmAssist] = useState(false);
  const [llmConfig, setLlmConfig] = useState<FileImportConfig | null>(null);
  const [job, setJob] = useState<FileImportJob | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getFileImportConfig()
      .then(setLlmConfig)
      .catch(() => setLlmConfig(null));
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function restoreJob() {
      try {
        const savedJobId = window.localStorage.getItem(lastJobStorageKey);
        if (savedJobId) {
          const savedJob = await getFileImportJob(savedJobId);
          if (!cancelled) {
            setJob(savedJob);
            return;
          }
        }
      } catch {
        window.localStorage.removeItem(lastJobStorageKey);
      }

      try {
        const recentJobs = await listFileImportJobs(10);
        const activeJob = recentJobs.find((item) => activeStatuses.has(item.status));
        if (!cancelled && activeJob) {
          setJob(activeJob);
          window.localStorage.setItem(lastJobStorageKey, activeJob.job_id);
        }
      } catch {
        // No job history available; the upload form still works.
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
        if (!cancelled) setJob(fresh);
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
  };

  const handleUpload = async (files: File[]) => {
    setUploading(true);
    setError(null);

    try {
      const created = await createFileImportJob(files, { use_llm_assist: useLlmAssist });
      window.localStorage.setItem(lastJobStorageKey, created.job_id);
      setJob(created);
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
          上传 PDF、Markdown、Word、LaTeX、结构化 JSON 或图片，系统会写入文件题库并重建向量索引
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

      <div className="rounded-lg border border-gray-200 bg-gray-50 p-5">
        <h3 className="text-sm font-semibold text-gray-700">支持的格式</h3>
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-5">
          {[
            { icon: '📄', label: 'PDF', desc: '转文本入库' },
            { icon: '📝', label: 'Markdown', desc: '原文入库' },
            { icon: '📃', label: 'Word', desc: '.docx' },
            { icon: '{}', label: 'JSON', desc: '题目/答案/资产' },
            { icon: '📐', label: 'LaTeX', desc: '原文入库' },
            { icon: '🖼️', label: '图片', desc: '需识别文本' },
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
