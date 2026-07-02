'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { AlertCircle, ArrowLeft, FileText, Image as ImageIcon } from 'lucide-react';
import type { FileQuestionDetail } from '@/lib/api';
import { getFileQuestion } from '@/lib/api';
import QuestionBodyRenderer from '@/components/QuestionBodyRenderer';

function formatLabel(format?: string | null) {
  if (format === 'latex') return 'LaTeX';
  if (format === 'text') return 'Text';
  return 'Markdown';
}

export default function FileQuestionDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [question, setQuestion] = useState<FileQuestionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadQuestion = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setQuestion(await getFileQuestion(id));
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取题目文件失败');
      setQuestion(null);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { loadQuestion(); }, [loadQuestion]);

  if (loading) {
    return (
      <div className="space-y-4">
        <Link href="/questions" className="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900">
          <ArrowLeft className="h-4 w-4" />返回题库
        </Link>
        <div className="h-64 animate-pulse rounded-lg bg-gray-100" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        <Link href="/questions" className="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900">
          <ArrowLeft className="h-4 w-4" />返回题库
        </Link>
        <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4">
          <AlertCircle className="mt-0.5 h-5 w-5 text-red-500" />
          <div>
            <p className="text-sm font-medium text-red-800">加载失败</p>
            <p className="mt-1 text-sm text-red-600">{error}</p>
            <button onClick={loadQuestion} className="mt-3 rounded-md bg-red-100 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-200">
              重试
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!question) {
    return (
      <div className="space-y-4">
        <Link href="/questions" className="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900">
          <ArrowLeft className="h-4 w-4" />返回题库
        </Link>
        <div className="text-center py-16">
          <FileText className="mx-auto h-12 w-12 text-gray-300" />
          <p className="mt-3 text-sm font-medium text-gray-500">题目文件不存在</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Link href="/questions" className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-gray-900">
        <ArrowLeft className="h-4 w-4" />返回题库
      </Link>

      {/* Header */}
      <div className="rounded-xl border border-gray-200 bg-white p-6">
        <h1 className="text-xl font-bold text-gray-900">{question.title || '（无标题）'}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-gray-500">
          <span className="font-mono text-xs text-gray-600">{question.question_id}</span>
          {question.question_format && (
            <span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700">
              Q: {formatLabel(question.question_format)}
            </span>
          )}
          {question.answer_format && (
            <span className="rounded-full bg-green-50 px-2.5 py-0.5 text-xs font-medium text-green-700">
              A: {formatLabel(question.answer_format)}
            </span>
          )}
          {question.indexed !== undefined && (
            <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${question.indexed ? 'bg-green-50 text-green-700' : 'bg-yellow-50 text-yellow-700'}`}>
              {question.indexed ? '已索引' : '未索引'}
            </span>
          )}
        </div>
      </div>

      {/* Question Body */}
      <div className="rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">题目正文</h2>
        <div className="prose prose-sm max-w-none text-gray-900">
          <QuestionBodyRenderer
            body={question.question_body}
            format={question.question_format || 'markdown'}
            questionId={question.question_id}
          />
        </div>
      </div>

      {/* Answer Body */}
      <div className="rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">答案正文</h2>
        <div className="prose prose-sm max-w-none text-gray-900">
          {question.answer_body ? (
            <QuestionBodyRenderer
              body={question.answer_body}
              format={question.answer_format || 'markdown'}
              questionId={question.question_id}
            />
          ) : (
            <p className="text-sm italic text-gray-400">未提供答案</p>
          )}
        </div>
      </div>

      {/* Assets */}
      {(question.assets || []).length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">图片资产</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            {question.assets.map((asset) => (
              <div key={asset.filename} className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-center">
                <ImageIcon className="mx-auto h-8 w-8 text-gray-400" />
                <p className="mt-1 text-xs text-gray-600 font-mono truncate">{asset.filename}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Metadata */}
      {question.metadata && Object.keys(question.metadata).length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">元数据</h2>
          <pre className="rounded-lg bg-gray-50 p-4 text-xs text-gray-700 overflow-x-auto">{JSON.stringify(question.metadata, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}
