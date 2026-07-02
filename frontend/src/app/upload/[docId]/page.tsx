'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import {
  ArrowLeft,
  CheckCircle,
  Clock,
  Eye,
  FileText,
  Loader2,
  Play,
  XCircle,
} from 'lucide-react';
import {
  getSourceDocument,
  getExtractionJob,
  getJobCandidates,
  processDocument,
  approveCandidate,
  rejectCandidate,
  batchApproveCandidates,
  type SourceDocumentDetail,
  type CandidateQuestion,
} from '@/lib/api';

const STATUS_BADGES: Record<string, string> = {
  pending: 'bg-gray-100 text-gray-700',
  running: 'bg-blue-100 text-blue-700',
  completed: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
};

const STATUS_LABELS: Record<string, string> = {
  pending: '等待处理',
  running: '处理中',
  completed: '已完成',
  failed: '失败',
};

const TYPE_LABELS: Record<string, string> = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  fill_blank: '填空题',
  calculation: '计算题',
  experiment: '实验题',
  essay: '简答题',
  composite: '综合题',
};

function CandidateCard({
  candidate,
  jobId,
  onApprove,
  onReject,
  onExpand,
  expanded,
}: {
  candidate: CandidateQuestion;
  jobId: string;
  onApprove: (index: number) => void;
  onReject: (index: number) => void;
  onExpand: (index: number) => void;
  expanded: boolean;
}) {
  const q = candidate.question as Record<string, unknown>;
  const stem = (q.stem as string) || '';
  const qType = (q.question_type as string) || 'calculation';
  const difficulty = (q.difficulty as number) || 3;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          {/* Header row */}
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center rounded bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
              #{candidate.index + 1}
            </span>
            <span className="inline-flex items-center rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
              {TYPE_LABELS[qType] || qType}
            </span>
            <span className="text-xs text-yellow-600">
              {'★'.repeat(difficulty)}{'☆'.repeat(5 - difficulty)}
            </span>
            <span
              className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${
                candidate.confidence >= 0.8
                  ? 'bg-green-100 text-green-700'
                  : candidate.confidence >= 0.5
                  ? 'bg-yellow-100 text-yellow-700'
                  : 'bg-red-100 text-red-700'
              }`}
            >
              置信度: {(candidate.confidence * 100).toFixed(0)}%
            </span>
          </div>

          {/* Stem preview */}
          <p className="line-clamp-2 text-sm text-gray-700">{stem}</p>

          {/* Warnings */}
          {candidate.warnings.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {candidate.warnings.map((w, i) => (
                <span
                  key={i}
                  className="inline-flex items-center rounded bg-yellow-50 px-1.5 py-0.5 text-xs text-yellow-700"
                >
                  ⚠ {w}
                </span>
              ))}
            </div>
          )}

          {/* Expanded detail */}
          {expanded && (
            <div className="mt-3 space-y-3 border-t border-gray-100 pt-3">
              {/* Options */}
              {Array.isArray(q.options) && (q.options as Array<Record<string, unknown>>).length > 0 && (
                <div>
                  <p className="text-xs font-medium text-gray-500">选项</p>
                  <ul className="mt-1 space-y-1">
                    {(q.options as Array<Record<string, unknown>>).map(
                      (opt: Record<string, unknown>, i: number) => (
                        <li
                          key={i}
                          className={`rounded px-2 py-1 text-xs ${
                            opt.is_correct
                              ? 'bg-green-50 text-green-700'
                              : 'text-gray-600'
                          }`}
                        >
                          {opt.option_label as string}. {opt.content as string}
                          {opt.is_correct ? ' ✓' : ''}
                        </li>
                      )
                    )}
                  </ul>
                </div>
              )}

              {/* Answer */}
              {Array.isArray(q.answers) && (q.answers as Array<Record<string, unknown>>).length > 0 && (
                <div>
                  <p className="text-xs font-medium text-gray-500">答案</p>
                  {(q.answers as Array<Record<string, unknown>>).map(
                    (ans: Record<string, unknown>, i: number) => (
                      <p key={i} className="mt-1 text-xs text-gray-700">
                        [{ans.answer_type as string}] {ans.content as string}
                        {ans.unit ? ` ${ans.unit}` : ''}
                      </p>
                    )
                  )}
                </div>
              )}

              {/* Solution */}
              {Array.isArray(q.solution_steps) && (q.solution_steps as Array<Record<string, unknown>>).length > 0 && (
                <div>
                  <p className="text-xs font-medium text-gray-500">解析步骤</p>
                  <ol className="mt-1 list-inside list-decimal space-y-1">
                    {(q.solution_steps as Array<Record<string, unknown>>).map(
                      (step: Record<string, unknown>, i: number) => (
                        <li key={i} className="text-xs text-gray-600">
                          {step.content as string}
                        </li>
                      )
                    )}
                  </ol>
                </div>
              )}

              {/* Knowledge Points */}
              {Array.isArray(q.knowledge_points) && (q.knowledge_points as Array<Record<string, unknown>>).length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {(q.knowledge_points as Array<Record<string, unknown>>).map(
                    (kp: Record<string, unknown>, i: number) => (
                      <span
                        key={i}
                        className="rounded bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700"
                      >
                        {kp.path as string}
                      </span>
                    )
                  )}
                </div>
              )}

              {/* Needs Review */}
              {candidate.needs_review.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-red-500">需要人工确认：</p>
                  <p className="text-xs text-red-400">
                    {candidate.needs_review.join(', ')}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Action buttons */}
      <div className="mt-3 flex items-center gap-2 border-t border-gray-100 pt-3">
        <button
          onClick={() => onExpand(candidate.index)}
          className="rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100"
        >
          <Eye className="mr-1 inline h-3 w-3" />
          {expanded ? '收起' : '展开'}
        </button>
        <div className="flex-1" />
        <button
          onClick={() => onReject(candidate.index)}
          className="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50"
        >
          <XCircle className="mr-1 inline h-3 w-3" />
          驳回
        </button>
        <button
          onClick={() => onApprove(candidate.index)}
          className="rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700"
        >
          <CheckCircle className="mr-1 inline h-3 w-3" />
          批准入库
        </button>
      </div>
    </div>
  );
}

export default function DocumentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const docId = params.docId as string;

  const [doc, setDoc] = useState<SourceDocumentDetail | null>(null);
  const [candidates, setCandidates] = useState<CandidateQuestion[]>([]);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const docData = await getSourceDocument(docId);
      setDoc(docData);

      // Get candidates from the latest completed job
      const completedJob = docData.extraction_jobs.find(
        (j) => j.status === 'completed'
      );
      if (completedJob) {
        const cands = await getJobCandidates(completedJob.job_id);
        setCandidates(cands);
      } else {
        setCandidates([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [docId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Poll for processing status
  useEffect(() => {
    if (!doc) return;
    const jobs = doc.extraction_jobs ?? [];
    const runningJobs = jobs.filter(
      (j) => j.status === 'pending' || j.status === 'running'
    );
    if (runningJobs.length === 0) return;

    const interval = setInterval(() => {
      fetchData();
    }, 3000);
    return () => clearInterval(interval);
  }, [doc, fetchData]);

  const handleProcess = async () => {
    setProcessing(true);
    try {
      await processDocument(docId);
      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : '处理失败');
    } finally {
      setProcessing(false);
    }
  };

  const handleApprove = async (index: number) => {
    try {
      const completedJob = doc?.extraction_jobs.find((j) => j.status === 'completed');
      if (!completedJob) return;
      await approveCandidate(completedJob.job_id, index);
      setActionMsg(`候选题 #${index + 1} 已批准入库（状态：待审核）`);
      // Refresh
      await fetchData();
      setTimeout(() => setActionMsg(null), 3000);
    } catch (err) {
      setActionMsg(`批准失败: ${err instanceof Error ? err.message : '未知错误'}`);
    }
  };

  const handleReject = async (index: number) => {
    try {
      const completedJob = doc?.extraction_jobs.find((j) => j.status === 'completed');
      if (!completedJob) return;
      await rejectCandidate(completedJob.job_id, index);
      setActionMsg(`候选题 #${index + 1} 已驳回`);
      await fetchData();
      setTimeout(() => setActionMsg(null), 3000);
    } catch (err) {
      setActionMsg(`驳回失败: ${err instanceof Error ? err.message : '未知错误'}`);
    }
  };

  const handleBatchApprove = async () => {
    try {
      const completedJob = doc?.extraction_jobs.find((j) => j.status === 'completed');
      if (!completedJob) return;
      const indices = candidates.map((c) => c.index);
      const result = await batchApproveCandidates(completedJob.job_id, indices);
      setActionMsg(`已批准 ${result.approved.length} 题，失败 ${result.errors.length} 题`);
      await fetchData();
      setTimeout(() => setActionMsg(null), 5000);
    } catch (err) {
      setActionMsg(`批量批准失败: ${err instanceof Error ? err.message : '未知错误'}`);
    }
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 animate-pulse rounded bg-gray-200" />
        <div className="h-32 animate-pulse rounded-xl bg-gray-100" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        <button
          onClick={() => router.push('/upload')}
          className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800"
        >
          <ArrowLeft className="h-4 w-4" />
          返回上传
        </button>
        <div className="rounded-lg border border-red-200 bg-red-50 p-4">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      </div>
    );
  }

  if (!doc) {
    return (
      <div className="space-y-4">
        <Link href="/upload" className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800">
          <ArrowLeft className="h-4 w-4" />返回上传
        </Link>
        <div className="rounded-xl border border-dashed border-gray-300 bg-white px-6 py-12 text-center">
          <FileText className="mx-auto h-10 w-10 text-gray-300" />
          <p className="mt-3 text-sm font-medium text-gray-500">文档不存在</p>
          <p className="mt-1 text-sm text-gray-400">该文档可能已被删除或 ID 不正确</p>
          <button
            onClick={fetchData}
            className="mt-3 rounded-md bg-blue-100 px-3 py-1.5 text-sm font-medium text-blue-700 hover:bg-blue-200"
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  const jobs = doc.extraction_jobs ?? [];
  const runningJobs = jobs.filter(
    (j) => j.status === 'pending' || j.status === 'running'
  );
  const completedJob = jobs.find((j) => j.status === 'completed');
  const hasFailed = jobs.some((j) => j.status === 'failed');
  const isProcessing = runningJobs.length > 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <button
            onClick={() => router.push('/upload')}
            className="mb-2 inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800"
          >
            <ArrowLeft className="h-4 w-4" />
            返回上传
          </button>
          <h1 className="text-2xl font-bold text-gray-900">
            {doc.original_filename || doc.document_id}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            ID: {doc.document_id} · 类型: {doc.source_type}
            {doc.page_count ? ` · ${doc.page_count} 页` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!completedJob && !isProcessing && (
            <button
              onClick={handleProcess}
              disabled={processing}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {processing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              开始解析
            </button>
          )}
          {candidates.length > 0 && (
            <button
              onClick={handleBatchApprove}
              className="inline-flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-700"
            >
              <CheckCircle className="h-4 w-4" />
              全部批准
            </button>
          )}
        </div>
      </div>

      {/* Action message */}
      {actionMsg && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
          <p className="text-sm text-blue-700">{actionMsg}</p>
        </div>
      )}

      {/* Processing Status */}
      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <h2 className="text-sm font-semibold text-gray-700">处理状态</h2>
        <div className="mt-3 space-y-2">
          {jobs.length === 0 && !isProcessing && (
            <p className="text-sm text-gray-400">尚未处理，点击「开始解析」启动处理管线</p>
          )}
          {isProcessing && (
            <div className="flex items-center gap-3 rounded-lg bg-blue-50 p-3">
              <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
              <div>
                <p className="text-sm font-medium text-blue-700">正在处理...</p>
                <p className="text-xs text-blue-500">
                  后台处理中，页面将自动刷新
                </p>
              </div>
            </div>
          )}
          {jobs.map((job) => (
            <div
              key={job.job_id}
              className="flex items-center gap-3 rounded-lg border border-gray-100 p-3"
            >
              <span
                className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_BADGES[job.status] || 'bg-gray-100 text-gray-600'}`}
              >
                {job.status === 'running' ? (
                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                ) : job.status === 'completed' ? (
                  <CheckCircle className="mr-1 h-3 w-3" />
                ) : job.status === 'failed' ? (
                  <XCircle className="mr-1 h-3 w-3" />
                ) : (
                  <Clock className="mr-1 h-3 w-3" />
                )}
                {STATUS_LABELS[job.status] || job.status}
              </span>
              <div className="flex-1">
                <p className="text-xs text-gray-600">
                  作业: {job.job_id} · 类型: {job.job_type}
                  {job.candidate_count > 0 ? ` · ${job.candidate_count} 个候选题` : ''}
                </p>
                {job.error_message && (
                  <p className="text-xs text-red-500">{job.error_message}</p>
                )}
              </div>
              <span className="text-xs text-gray-400">
                {new Date(job.created_at).toLocaleString('zh-CN')}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Candidates */}
      <div>
        <h2 className="mb-3 text-lg font-semibold text-gray-900">
          候选题 ({candidates.length})
        </h2>
        {candidates.length === 0 && completedJob && (
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-8 text-center">
            <p className="text-sm text-gray-500">未提取到候选题</p>
            <p className="mt-1 text-xs text-gray-400">
              请检查原文件是否包含物理题目内容
            </p>
          </div>
        )}
        <div className="space-y-3">
          {candidates.map((c) => (
            <CandidateCard
              key={c.index}
              candidate={c}
              jobId={completedJob?.job_id || ''}
              onApprove={handleApprove}
              onReject={handleReject}
              onExpand={(idx) => setExpandedIdx(expandedIdx === idx ? null : idx)}
              expanded={expandedIdx === c.index}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
