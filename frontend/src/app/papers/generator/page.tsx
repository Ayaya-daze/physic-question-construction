'use client';

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Download,
  FileText,
  Image as ImageIcon,
  Loader2,
  RefreshCw,
  Search,
} from 'lucide-react';
import type { FileQuestionSummary } from '@/lib/api';
import { exportFilePaper, getFileQuestions } from '@/lib/api';

export const dynamic = 'force-dynamic';

type ExportResult = Awaited<ReturnType<typeof exportFilePaper>>;

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function FilePaperGeneratorContent() {
  const [title, setTitle] = useState('文件题库组卷');
  const [query, setQuery] = useState('');
  const [questionCount, setQuestionCount] = useState('1');
  const [questions, setQuestions] = useState<FileQuestionSummary[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportResult, setExportResult] = useState<ExportResult | null>(null);

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedQuestions = questions.filter((question) => selectedSet.has(question.question_id));

  const loadQuestions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getFileQuestions({
        q: query.trim() || undefined,
        limit: 200,
      });
      setQuestions(result.items ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取题库文件失败');
      setQuestions([]);
    } finally {
      setLoading(false);
    }
  }, [query]);

  useEffect(() => {
    loadQuestions();
  }, [loadQuestions]);

  const toggleQuestion = (questionId: string) => {
    setSelectedIds((current) =>
      current.includes(questionId)
        ? current.filter((item) => item !== questionId)
        : [...current, questionId],
    );
  };

  const handleExport = async () => {
    const count = Number(questionCount);
    if (!title.trim()) {
      setError('请填写试卷标题');
      return;
    }
    if (selectedIds.length === 0 && !query.trim()) {
      setError('请选择题目，或填写相关知识点/搜索词后按题目数自动选题');
      return;
    }

    setExporting(true);
    setError(null);
    setExportResult(null);
    try {
      const result = await exportFilePaper({
        title: title.trim(),
        question_ids: selectedIds,
        search_query: query.trim() || undefined,
        question_count: Number.isFinite(count) && count > 0 ? count : undefined,
      });
      setExportResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : '导出失败');
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link href="/questions" className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors">
        <ArrowLeft className="h-4 w-4" />返回题库
      </Link>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">文件题库组卷</h1>
          <p className="mt-1 text-sm text-gray-500">
            从题目文件读取正文、答案和图片，导出 TeX 源文件与 PDF
          </p>
        </div>
        <button
          onClick={handleExport}
          disabled={exporting}
          className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
          导出试卷
        </button>
      </div>

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr_0.7fr]">
          <label className="block">
            <span className="text-sm font-medium text-gray-700">试卷标题</span>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm focus:border-gray-900 focus:outline-none focus:ring-1 focus:ring-gray-900"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-gray-700">相关知识点 / 搜索词</span>
            <div className="relative mt-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') loadQuestions();
                }}
                placeholder="例如 牛顿第二定律"
                className="w-full rounded-lg border border-gray-300 py-2.5 pl-10 pr-3 text-sm focus:border-gray-900 focus:outline-none focus:ring-1 focus:ring-gray-900"
              />
            </div>
          </label>
          <label className="block">
            <span className="text-sm font-medium text-gray-700">题目数</span>
            <input
              type="number"
              min={1}
              max={200}
              value={questionCount}
              onChange={(event) => setQuestionCount(event.target.value)}
              className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm focus:border-gray-900 focus:outline-none focus:ring-1 focus:ring-gray-900"
            />
          </label>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-gray-500">导出会生成独立的题目卷和答案卷，不把答案混入题目卷。</p>
          <button
            onClick={loadQuestions}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-60"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            搜索题库
          </button>
        </div>
      </section>

      {error && (
        <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4">
          <AlertCircle className="mt-0.5 h-5 w-5 text-red-500" />
          <div>
            <p className="text-sm font-medium text-red-800">操作失败</p>
            <p className="mt-1 text-sm text-red-600">{error}</p>
          </div>
        </div>
      )}

      {exportResult && (
        <section className="rounded-lg border border-green-200 bg-green-50 p-5">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 h-5 w-5 text-green-600" />
            <div className="flex-1">
              <p className="text-sm font-semibold text-green-900">
                {exportResult.status === 'succeeded' ? 'PDF 已生成' : '已生成 TeX，PDF 编译未成功'}
              </p>
              <p className="mt-1 text-sm text-green-800">
                使用 {exportResult.question_count} 道题：{exportResult.question_ids.join(', ')}
              </p>

              {/* Question paper downloads */}
              <div className="mt-3">
                <p className="text-xs font-semibold text-gray-500 uppercase mb-1.5">题目卷</p>
                <div className="flex flex-wrap gap-2">
                  <a href={exportResult.question_tex_url} target="_blank" className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-2 text-sm font-medium text-gray-900 ring-1 ring-green-200 hover:bg-green-100">
                    <FileText className="h-4 w-4" />questions.tex
                  </a>
                  {exportResult.question_pdf_url && (
                    <a href={exportResult.question_pdf_url} target="_blank" className="inline-flex items-center gap-1.5 rounded-lg bg-green-700 px-3 py-2 text-sm font-medium text-white hover:bg-green-800">
                      <Download className="h-4 w-4" />questions.pdf
                    </a>
                  )}
                  {exportResult.question_build_log_url && (
                    <a href={exportResult.question_build_log_url} target="_blank" className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-2 text-sm font-medium text-gray-700 ring-1 ring-green-200 hover:bg-green-100">
                      编译日志
                    </a>
                  )}
                </div>
              </div>

              {/* Answer paper downloads */}
              <div className="mt-3">
                <p className="text-xs font-semibold text-gray-500 uppercase mb-1.5">答案卷</p>
                <div className="flex flex-wrap gap-2">
                  <a href={exportResult.answer_tex_url} target="_blank" className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-2 text-sm font-medium text-gray-900 ring-1 ring-green-200 hover:bg-green-100">
                    <FileText className="h-4 w-4" />answers.tex
                  </a>
                  {exportResult.answer_pdf_url && (
                    <a href={exportResult.answer_pdf_url} target="_blank" className="inline-flex items-center gap-1.5 rounded-lg bg-green-700 px-3 py-2 text-sm font-medium text-white hover:bg-green-800">
                      <Download className="h-4 w-4" />answers.pdf
                    </a>
                  )}
                  {exportResult.answer_build_log_url && (
                    <a href={exportResult.answer_build_log_url} target="_blank" className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-2 text-sm font-medium text-gray-700 ring-1 ring-green-200 hover:bg-green-100">
                      编译日志
                    </a>
                  )}
                </div>
              </div>
            </div>
          </div>
        </section>
      )}

      {selectedIds.length > 0 && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <h2 className="text-sm font-semibold text-gray-900">已选题目</h2>
          <div className="mt-3 flex flex-wrap gap-2">
            {selectedIds.map((questionId) => (
              <button
                key={questionId}
                onClick={() => toggleQuestion(questionId)}
                className="rounded-full bg-gray-900 px-3 py-1.5 font-mono text-xs text-white hover:bg-gray-700"
              >
                {questionId} ×
              </button>
            ))}
          </div>
          {selectedQuestions.length > 0 && (
            <p className="mt-3 text-sm text-gray-500">
              当前列表中已选 {selectedQuestions.length} 道，可继续搜索补充。
            </p>
          )}
        </section>
      )}

      <section className="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-gray-900">题库文件</h2>
        </div>
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">选择</th>
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">题目</th>
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">预览</th>
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">资产</th>
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">更新时间</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading && Array.from({ length: 4 }).map((_, idx) => (
              <tr key={idx} className="animate-pulse">
                <td className="px-4 py-4"><div className="h-4 w-4 rounded bg-gray-200" /></td>
                <td className="px-4 py-4"><div className="h-4 w-48 rounded bg-gray-200" /></td>
                <td className="px-4 py-4"><div className="h-4 w-96 rounded bg-gray-200" /></td>
                <td className="px-4 py-4"><div className="h-4 w-12 rounded bg-gray-200" /></td>
                <td className="px-4 py-4"><div className="h-4 w-32 rounded bg-gray-200" /></td>
              </tr>
            ))}

            {!loading && questions.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-16 text-center">
                  <FileText className="mx-auto h-12 w-12 text-gray-300" />
                  <p className="mt-3 text-sm font-medium text-gray-500">没有匹配的题目文件</p>
                </td>
              </tr>
            )}

            {!loading && questions.map((question) => {
              const selected = selectedSet.has(question.question_id);
              return (
                <tr key={question.question_id} className={selected ? 'bg-gray-50' : 'hover:bg-gray-50'}>
                  <td className="px-4 py-4 align-top">
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={() => toggleQuestion(question.question_id)}
                      className="h-4 w-4 rounded border-gray-300 text-gray-900 focus:ring-gray-900"
                    />
                  </td>
                  <td className="px-4 py-4 align-top">
                    <Link
                      href={`/questions/files/${question.question_id}`}
                      className="font-mono text-sm font-medium text-gray-900 hover:text-blue-700"
                    >
                      {question.question_id}
                    </Link>
                    <p className="mt-1 text-sm font-semibold text-gray-800">{question.title}</p>
                  </td>
                  <td className="max-w-xl px-4 py-4 align-top text-sm leading-6 text-gray-600">
                    {question.preview || '无正文预览'}
                  </td>
                  <td className="px-4 py-4 align-top">
                    <span className="inline-flex items-center gap-1 rounded-full border border-gray-200 px-2.5 py-1 text-xs text-gray-600">
                      <ImageIcon className="h-3.5 w-3.5" />
                      {(question.assets ?? []).length}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-4 align-top text-sm text-gray-500">
                    {formatDate(question.updated_at)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </div>
  );
}

export default function FilePaperGeneratorPage() {
  return (
    <Suspense fallback={<div className="h-24 animate-pulse rounded-lg bg-gray-100" />}>
      <FilePaperGeneratorContent />
    </Suspense>
  );
}
