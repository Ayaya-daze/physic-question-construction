'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { AlertCircle, ArrowLeft, BookOpen, CheckCircle, Clock, Hash, Loader2, Star, Tag } from 'lucide-react';
import { getQuestion, getQuestionContent, type Question } from '@/lib/api';
import QuestionBodyRenderer from '@/components/QuestionBodyRenderer';

const questionTypeLabels: Record<string, string> = {
  single_choice: '单选题', multiple_choice: '多选题', fill_blank: '填空题',
  calculation: '计算题', experiment: '实验题', essay: '简答题', composite: '综合题',
};

const statusConfig: Record<string, { label: string; className: string }> = {
  draft: { label: '草稿', className: 'bg-gray-100 text-gray-700' },
  pending_review: { label: '待审核', className: 'bg-yellow-100 text-yellow-700' },
  approved: { label: '已通过', className: 'bg-green-100 text-green-700' },
  rejected: { label: '已驳回', className: 'bg-red-100 text-red-700' },
  archived: { label: '已归档', className: 'bg-blue-100 text-blue-700' },
};

function DifficultyStars({ difficulty }: { difficulty: number }) {
  return (
    <span className="inline-flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((star) =>
        star <= difficulty ? <Star key={star} className="h-4 w-4 fill-yellow-400 text-yellow-400" /> :
          <Star key={star} className="h-4 w-4 text-gray-300" />
      )}
    </span>
  );
}

function formatDate(iso: string) { return new Date(iso).toLocaleString('zh-CN'); }

export default function QuestionDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [question, setQuestion] = useState<Question | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [q, contentResult] = await Promise.all([
          getQuestion(id).catch(() => null),
          getQuestionContent(id).catch(() => null),
        ]);
        if (cancelled) return;
        if (!q) { setError('题目不存在'); setQuestion(null); return; }
        setQuestion(q);
        if (contentResult?.content) setFileContent(contentResult.content);
      } catch (err) {
        if (!cancelled) { setError(err instanceof Error ? err.message : '加载失败'); setQuestion(null); }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [id]);

  const retry = useCallback(() => {
    setLoading(true); setError(null);
    Promise.all([
      getQuestion(id).catch(() => null),
      getQuestionContent(id).catch(() => null),
    ]).then(([q, c]) => {
      if (!q) { setError('Question not found'); return; }
      setQuestion(q);
      if (c?.content) setFileContent(c.content);
    }).catch(err => setError(err instanceof Error ? err.message : '重试失败'))
    .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div className="space-y-4">
        <Link href="/questions" className="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900"><ArrowLeft className="h-4 w-4" />返回题库</Link>
        <div className="h-64 animate-pulse rounded-lg bg-gray-100" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        <Link href="/questions" className="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900"><ArrowLeft className="h-4 w-4" />返回题库</Link>
        <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4">
          <AlertCircle className="mt-0.5 h-5 w-5 text-red-500" />
          <div>
            <p className="text-sm font-medium text-red-800">加载失败</p>
            <p className="mt-1 text-sm text-red-600">{error}</p>
            <button onClick={retry} className="mt-3 rounded-md bg-red-100 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-200">重试</button>
          </div>
        </div>
      </div>
    );
  }

  if (!question) {
    return (
      <div className="space-y-4">
        <Link href="/questions" className="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900"><ArrowLeft className="h-4 w-4" />返回题库</Link>
        <div className="text-center py-16">
          <BookOpen className="mx-auto h-12 w-12 text-gray-300" />
          <p className="mt-3 text-sm font-medium text-gray-500">题目不存在</p>
          <p className="mt-1 text-sm text-gray-400">该题目可能已被删除或 ID 不正确</p>
        </div>
      </div>
    );
  }

  const statusCfg = statusConfig[question.status] ?? statusConfig.draft;
  const qOptions = question.options ?? question.choice_options ?? [];
  const qAnswers = question.answers ?? [];
  const qSolutions = question.solution_steps ?? [];
  const qKnowledgePoints = question.knowledge_points ?? [];
  const qTags = question.tags ?? [];

  return (
    <div className="space-y-6">
      <Link href="/questions" className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors">
        <ArrowLeft className="h-4 w-4" />返回题库
      </Link>

      {/* Header */}
      <div className="rounded-xl border border-gray-200 bg-white p-6">
        <div className="flex flex-wrap items-start gap-4 justify-between">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-gray-900">
                {questionTypeLabels[question.question_type] || question.question_type}
              </h1>
              <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${statusCfg.className}`}>{statusCfg.label}</span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-gray-500">
              <span className="flex items-center gap-1"><Hash className="h-3.5 w-3.5" />{question.canonical_id}</span>
              <span className="flex items-center gap-1"><DifficultyStars difficulty={question.difficulty} /></span>
              {question.grade && <span>年级: {question.grade}</span>}
              <span className="flex items-center gap-1"><Clock className="h-3.5 w-3.5" />{formatDate(question.created_at)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Stem */}
      <div className="rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">题干</h2>
        <div className="prose prose-sm max-w-none text-gray-900">
          <QuestionBodyRenderer body={question.stem || ''} format="markdown" questionId={question.canonical_id || String(id)} />
        </div>
      </div>

      {/* Options (if any) */}
      {qOptions.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">选项</h2>
          <div className="space-y-2">
            {qOptions.map((opt, idx) => (
              <div key={idx} className={`flex items-start gap-3 rounded-lg border px-4 py-3 ${opt.is_correct ? 'border-green-300 bg-green-50' : 'border-gray-200'}`}>
                <span className={`flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full text-xs font-bold ${opt.is_correct ? 'bg-green-500 text-white' : 'bg-gray-100 text-gray-600'}`}>
                  {opt.option_label}
                </span>
                <span className="text-sm text-gray-900">
                  <QuestionBodyRenderer body={opt.content} format="markdown" questionId={question.canonical_id || String(id)} />
                </span>
                {opt.is_correct && <CheckCircle className="h-4 w-4 flex-shrink-0 text-green-600 ml-auto" />}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Answers */}
      {qAnswers.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">答案</h2>
          <div className="space-y-3">
            {qAnswers.map((ans, idx) => (
              <div key={idx} className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-medium text-blue-600 uppercase">{ans.answer_type || '答案'}</span>
                  {ans.unit && <span className="text-xs text-blue-500">单位: {ans.unit}</span>}
                </div>
                <p className="text-sm font-semibold text-gray-900">
                  <QuestionBodyRenderer body={ans.content} format="markdown" questionId={question.canonical_id || String(id)} />
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Solution Steps */}
      {qSolutions.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">解析步骤</h2>
          <div className="space-y-4">
            {qSolutions.map((step, idx) => (
              <div key={idx} className="flex gap-3">
                <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-gray-100 text-xs font-bold text-gray-600 mt-0.5">
                  {step.step_order ?? idx + 1}
                </span>
                <div className="flex-1 space-y-1.5">
                  <p className="text-sm text-gray-900">
                    <QuestionBodyRenderer body={step.content} format="markdown" questionId={question.canonical_id || String(id)} />
                  </p>
                  {step.formula && (
                    <p className="rounded bg-gray-50 px-3 py-1.5 font-mono text-sm text-gray-700">
                      <QuestionBodyRenderer body={step.formula} format="markdown" questionId={question.canonical_id || String(id)} />
                    </p>
                  )}
                  {step.explanation && (
                    <p className="text-sm italic text-gray-500">
                      <QuestionBodyRenderer body={step.explanation} format="markdown" questionId={question.canonical_id || String(id)} />
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Knowledge Points */}
      {qKnowledgePoints.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">知识点</h2>
          <div className="flex flex-wrap gap-2">
            {qKnowledgePoints.map((kp: { path: string; weight?: number; is_primary?: boolean }, idx: number) => (
              <span key={idx} className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium ${
                kp.is_primary ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-gray-200 bg-gray-50 text-gray-600'
              }`}>
                {kp.is_primary && <Star className="h-3 w-3" />}
                {kp.path}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Tags */}
      {qTags.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">标签</h2>
          <div className="flex flex-wrap gap-2">
            {qTags.map((tag: string) => (
              <span key={tag} className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600">
                <Tag className="h-3 w-3" />{tag}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* File content (if exists) */}
      {fileContent && (
        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">文件原文</h2>
          <pre className="rounded-lg bg-gray-50 p-4 text-sm text-gray-700 overflow-x-auto whitespace-pre-wrap">{fileContent.substring(0, 8000)}{fileContent.length > 8000 ? '\n\n... (truncated)' : ''}</pre>
        </div>
      )}
    </div>
  );
}
