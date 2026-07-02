'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, CheckCircle, Loader2, XCircle } from 'lucide-react';
import {
  getQuestion,
  approveQuestion,
  rejectQuestion,
  type Question,
} from '@/lib/api';

const TYPE_LABELS: Record<string, string> = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  fill_blank: '填空题',
  calculation: '计算题',
  experiment: '实验题',
  essay: '简答题',
  composite: '综合题',
};

const STATUS_COLORS: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-700',
  pending_review: 'bg-yellow-100 text-yellow-700',
  approved: 'bg-green-100 text-green-700',
  rejected: 'bg-red-100 text-red-700',
  archived: 'bg-blue-100 text-blue-700',
};

const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  pending_review: '待审核',
  approved: '已通过',
  rejected: '已驳回',
  archived: '已归档',
};

export default function ReviewDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const [question, setQuestion] = useState<Question | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const fetchQuestion = useCallback(async () => {
    try {
      const q = await getQuestion(id);
      setQuestion(q);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchQuestion();
  }, [fetchQuestion]);

  const handleApprove = async () => {
    setActionLoading(true);
    try {
      await approveQuestion(Number(id));
      setActionMsg('题目已审核通过');
      setTimeout(() => router.push('/review'), 1500);
    } catch (err) {
      setActionMsg(`操作失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleReject = async () => {
    const reason = prompt('驳回原因（可选）：');
    setActionLoading(true);
    try {
      await rejectQuestion(Number(id), reason || undefined);
      setActionMsg('题目已驳回');
      setTimeout(() => router.push('/review'), 1500);
    } catch (err) {
      setActionMsg(`操作失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-32 animate-pulse rounded bg-gray-200" />
        <div className="h-64 animate-pulse rounded-xl bg-gray-100" />
      </div>
    );
  }

  if (error || !question) {
    return (
      <div className="space-y-4">
        <button
          onClick={() => router.push('/review')}
          className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800"
        >
          <ArrowLeft className="h-4 w-4" />
          返回审核列表
        </button>
        <div className="rounded-lg border border-red-200 bg-red-50 p-4">
          <p className="text-sm text-red-700">{error || '题目不存在'}</p>
        </div>
      </div>
    );
  }

  // Only show review actions for pending_review questions
  const showReviewActions = question.status === 'pending_review';
  const choiceOptions = question.options ?? question.choice_options ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <button
            onClick={() => router.push('/review')}
            className="mb-2 inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800"
          >
            <ArrowLeft className="h-4 w-4" />
            返回审核列表
          </button>
          <h1 className="text-2xl font-bold text-gray-900">题目审核</h1>
        </div>
        {showReviewActions && (
          <div className="flex items-center gap-2">
            <button
              onClick={handleReject}
              disabled={actionLoading}
              className="inline-flex items-center gap-2 rounded-lg border border-red-200 px-4 py-2 text-sm font-semibold text-red-600 hover:bg-red-50 disabled:opacity-50"
            >
              {actionLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <XCircle className="h-4 w-4" />
              )}
              驳回
            </button>
            <button
              onClick={handleApprove}
              disabled={actionLoading}
              className="inline-flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50"
            >
              {actionLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle className="h-4 w-4" />
              )}
              批准通过
            </button>
          </div>
        )}
      </div>

      {/* Action message */}
      {actionMsg && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
          <p className="text-sm text-blue-700">{actionMsg}</p>
        </div>
      )}

      {/* Question metadata */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm font-mono text-gray-500">
          {question.canonical_id}
        </span>
        <span className="inline-flex items-center rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
          {TYPE_LABELS[question.question_type] || question.question_type}
        </span>
        <span
          className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[question.status]}`}
        >
          {STATUS_LABELS[question.status] || question.status}
        </span>
        <span className="text-xs text-yellow-600">
          {'★'.repeat(question.difficulty)}{'☆'.repeat(5 - question.difficulty)}
        </span>
        {question.grade && (
          <span className="inline-flex items-center rounded bg-purple-50 px-2 py-0.5 text-xs font-medium text-purple-600">
            {question.grade}
          </span>
        )}
      </div>

      {/* Stem */}
      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-gray-500">题干</h2>
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-900">
          {question.stem}
        </p>
      </div>

      {/* Options */}
      {choiceOptions.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <h2 className="mb-3 text-sm font-semibold text-gray-500">选项</h2>
          <ul className="space-y-2">
            {choiceOptions.map((opt, i) => {
              const correctAnswer = question.answers?.[0]?.content?.trim();
              const isCorrect = opt.is_correct || (correctAnswer && opt.option_label === correctAnswer);
              return (
              <li
                key={i}
                className={`flex items-center gap-3 rounded-lg border p-3 text-sm ${
                  isCorrect
                    ? 'border-green-300 bg-green-50'
                    : 'border-gray-100'
                }`}
              >
                <span
                  className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-medium ${
                    isCorrect
                      ? 'bg-green-500 text-white'
                      : 'bg-gray-100 text-gray-600'
                  }`}
                >
                  {opt.option_label}
                </span>
                <span
                  className={
                    isCorrect
                      ? 'font-medium text-green-800'
                      : 'text-gray-700'
                  }
                >
                  {opt.content}
                </span>
                {isCorrect && (
                  <CheckCircle className="ml-auto h-4 w-4 text-green-500" />
                )}
              </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Answer */}
      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-gray-500">答案</h2>
        <div className="flex flex-wrap gap-2">
          {question.answers?.[0]?.answer_type && (
            <span className="inline-flex items-center rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500">
              {question.answers[0].answer_type}
            </span>
          )}
          <p className="text-sm text-gray-900">{question.answers?.[0]?.content}</p>
          {question.answers?.[0]?.unit && (
            <span className="inline-flex items-center rounded bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-600">
              {question.answers[0].unit}
            </span>
          )}
          {question.answers?.[0]?.significant_figures !== undefined && (
            <span className="inline-flex items-center rounded bg-gray-50 px-2 py-0.5 text-xs font-medium text-gray-500">
              {question.answers[0].significant_figures}
            </span>
          )}
        </div>
      </div>

      {/* Solution */}
      {question.solution_steps && question.solution_steps.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <h2 className="mb-3 text-sm font-semibold text-gray-500">解析</h2>
          <div className="space-y-3">
            {question.solution_steps.map((step, i) => (
              <div key={i} className="flex gap-3">
                <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-blue-100 text-xs font-medium text-blue-700">
                  {step.step_order}
                </span>
                <div>
                  <p className="text-sm text-gray-700">{step.content}</p>
                  {step.formula && (
                    <code className="mt-1 inline-block rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                      {step.formula}
                    </code>
                  )}
                  {step.explanation && (
                    <p className="mt-1 text-xs text-gray-500">{step.explanation}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Knowledge Points */}
      {question.knowledge_points && question.knowledge_points.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <h2 className="mb-3 text-sm font-semibold text-gray-500">知识点</h2>
          <div className="flex flex-wrap gap-2">
            {question.knowledge_points.map((kp, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1 rounded bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-700"
              >
                {kp.path}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Tags */}
      {question.tags && question.tags.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <h2 className="mb-3 text-sm font-semibold text-gray-500">标签</h2>
          <div className="flex flex-wrap gap-2">
            {question.tags.map((tag, i) => (
              <span
                key={i}
                className="rounded bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600"
              >
                {tag}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Source */}
      {(question.source_document || question.source_document_id) && (
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <h2 className="mb-3 text-sm font-semibold text-gray-500">来源</h2>
          <div className="space-y-1 text-xs text-gray-500">
            {question.source_document && <p>文档: {question.source_document}</p>}
            {question.source_document_id && (
              <p>文档 ID: {question.source_document_id}</p>
            )}
            {question.source_page && <p>页码: {question.source_page}</p>}
          </div>
        </div>
      )}
    </div>
  );
}
