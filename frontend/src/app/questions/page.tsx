'use client';

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Image as ImageIcon,
  RefreshCw,
  Search,
} from 'lucide-react';
import { getFileQuestions, type FileQuestionSummary } from '@/lib/api';

export const dynamic = 'force-dynamic';

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function metadataList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0);
}

function FileQuestionRow({ question }: { question: FileQuestionSummary }) {
  const knowledgePoints = metadataList(question.metadata?.knowledge_points).slice(0, 4);
  const tags = metadataList(question.metadata?.tags).slice(0, 3);

  return (
    <tr className="transition-colors hover:bg-gray-50">
      <td className="px-4 py-3 align-top">
        <Link
          href={`/questions/files/${encodeURIComponent(question.question_id)}`}
          className="font-mono text-xs font-medium text-gray-700 hover:text-gray-950"
        >
          {question.question_id}
        </Link>
        <div className="mt-2 flex items-center gap-2">
          {question.indexed ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">
              <CheckCircle2 className="h-3 w-3" />
              已索引
            </span>
          ) : (
            <span className="rounded-full bg-yellow-50 px-2 py-0.5 text-xs font-medium text-yellow-700">
              未索引
            </span>
          )}
          {question.assets.length > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
              <ImageIcon className="h-3 w-3" />
              {question.assets.length}
            </span>
          )}
        </div>
      </td>
      <td className="px-4 py-3 align-top">
        <Link
          href={`/questions/files/${encodeURIComponent(question.question_id)}`}
          className="text-sm font-semibold text-gray-950 hover:text-gray-700"
        >
          {question.title || '（无标题）'}
        </Link>
        <p className="mt-1 line-clamp-2 text-sm leading-6 text-gray-600">
          {question.preview || '无预览文本'}
        </p>
        {(knowledgePoints.length > 0 || tags.length > 0) && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {knowledgePoints.map((item) => (
              <span key={item} className="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700">
                {item}
              </span>
            ))}
            {tags.map((item) => (
              <span key={item} className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                {item}
              </span>
            ))}
          </div>
        )}
      </td>
      <td className="whitespace-nowrap px-4 py-3 align-top text-sm text-gray-500">
        {formatDate(question.updated_at)}
      </td>
    </tr>
  );
}

function QuestionsPageContent() {
  const [query, setQuery] = useState('');
  const [submittedQuery, setSubmittedQuery] = useState('');
  const [questions, setQuestions] = useState<FileQuestionSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pageSize = 20;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const indexedCount = useMemo(() => questions.filter((item) => item.indexed).length, [questions]);

  const loadQuestions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getFileQuestions({
        q: submittedQuery.trim() || undefined,
        skip: (page - 1) * pageSize,
        limit: pageSize,
      });
      setQuestions(result.items ?? []);
      setTotal(result.total ?? 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取文件题库失败');
      setQuestions([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, submittedQuery]);

  useEffect(() => {
    loadQuestions();
  }, [loadQuestions]);

  const submitSearch = () => {
    setPage(1);
    setSubmittedQuery(query);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-950">文件题库</h1>
          <p className="mt-1 text-sm text-gray-500">
            共 {total} 道文件题目，当前页 {indexedCount} 道已索引
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/upload"
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-800 hover:bg-gray-50"
          >
            导入
          </Link>
          <Link
            href="/papers/generator"
            className="inline-flex items-center gap-2 rounded-lg bg-gray-950 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800"
          >
            组卷
          </Link>
        </div>
      </div>

      <section className="rounded-lg border border-gray-200 bg-white p-4">
        <div className="flex flex-wrap gap-3">
          <div className="relative min-w-[240px] flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') submitSearch();
              }}
              placeholder="搜索题目正文、答案、知识点或来源"
              className="w-full rounded-lg border border-gray-300 py-2.5 pl-10 pr-3 text-sm focus:border-gray-950 focus:outline-none focus:ring-1 focus:ring-gray-950"
            />
          </div>
          <button
            onClick={submitSearch}
            className="inline-flex items-center gap-2 rounded-lg bg-gray-950 px-4 py-2.5 text-sm font-medium text-white hover:bg-gray-800"
          >
            <Search className="h-4 w-4" />
            搜索
          </button>
          <button
            onClick={loadQuestions}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-60"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </button>
        </div>
      </section>

      {error && (
        <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4">
          <AlertCircle className="mt-0.5 h-5 w-5 text-red-500" />
          <div>
            <p className="text-sm font-medium text-red-800">加载失败</p>
            <p className="mt-1 text-sm text-red-600">{error}</p>
            <button
              onClick={loadQuestions}
              className="mt-2 rounded-md bg-red-100 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-200"
            >
              重试
            </button>
          </div>
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="w-56 px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">文件 ID</th>
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">题目</th>
              <th className="w-44 px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">更新时间</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading && Array.from({ length: 5 }).map((_, idx) => (
              <tr key={idx} className="animate-pulse">
                <td className="px-4 py-4"><div className="h-4 rounded bg-gray-200" /></td>
                <td className="px-4 py-4"><div className="h-4 rounded bg-gray-200" /></td>
                <td className="px-4 py-4"><div className="h-4 rounded bg-gray-200" /></td>
              </tr>
            ))}

            {!loading && questions.length === 0 && (
              <tr>
                <td colSpan={3} className="px-4 py-16 text-center">
                  <FileText className="mx-auto h-12 w-12 text-gray-300" />
                  <p className="mt-3 text-sm font-medium text-gray-500">没有文件题目</p>
                  <p className="mt-1 text-sm text-gray-400">导入题目或换一个搜索词</p>
                </td>
              </tr>
            )}

            {!loading && questions.map((question) => (
              <FileQuestionRow key={question.question_id} question={question} />
            ))}
          </tbody>
        </table>

        {!loading && total > 0 && (
          <div className="flex items-center justify-between border-t border-gray-200 px-4 py-3">
            <span className="text-sm text-gray-600">第 {page} / {totalPages} 页，共 {total} 条</span>
            <div className="flex gap-2">
              <button
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                disabled={page <= 1}
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
              >
                上一页
              </button>
              <button
                onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                disabled={page >= totalPages}
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
              >
                下一页
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function QuestionsPage() {
  return (
    <Suspense fallback={<div className="h-24 animate-pulse rounded-lg bg-gray-100" />}>
      <QuestionsPageContent />
    </Suspense>
  );
}
