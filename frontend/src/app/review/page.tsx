'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { CheckCircle, Eye, Search, XCircle } from 'lucide-react';
import {
  getPendingReviews,
  getPendingCount,
  approveQuestion,
  rejectQuestion,
  type PendingQuestion,
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

export default function ReviewPage() {
  const router = useRouter();
  const [questions, setQuestions] = useState<PendingQuestion[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const pageSize = 20;

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getPendingReviews({
        skip: page * pageSize,
        limit: pageSize,
        q: search || undefined,
      });
      setQuestions(res.items ?? []);
      setTotal(res.total ?? 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [page, search]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleApprove = async (id: number) => {
    try {
      await approveQuestion(id);
      setActionMsg(`题目 #${id} 已审核通过`);
      await fetchData();
      setTimeout(() => setActionMsg(null), 3000);
    } catch (err) {
      setActionMsg(`操作失败: ${err instanceof Error ? err.message : '未知错误'}`);
    }
  };

  const handleReject = async (id: number) => {
    const reason = prompt('驳回原因（可选）：');
    try {
      await rejectQuestion(id, reason || undefined);
      setActionMsg(`题目 #${id} 已驳回`);
      await fetchData();
      setTimeout(() => setActionMsg(null), 3000);
    } catch (err) {
      setActionMsg(`操作失败: ${err instanceof Error ? err.message : '未知错误'}`);
    }
  };

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">审核中心</h1>
        <p className="mt-1 text-sm text-gray-500">
          审核来自外部导入、OCR 识别、LLM 结构化的待审核题目
        </p>
      </div>

      {/* Action message */}
      {actionMsg && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
          <p className="text-sm text-blue-700">{actionMsg}</p>
        </div>
      )}

      {/* Search */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') fetchData();
            }}
            placeholder="搜索待审核题目..."
            className="w-full rounded-lg border border-gray-300 py-2 pl-10 pr-4 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
        <button
          onClick={fetchData}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          搜索
        </button>
      </div>

      {/* Table */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="h-16 animate-pulse rounded-lg bg-gray-100"
            />
          ))}
        </div>
      ) : error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4">
          <p className="text-sm text-red-700">{error}</p>
          <button
            onClick={fetchData}
            className="mt-2 text-sm font-medium text-red-600 hover:text-red-800"
          >
            重试
          </button>
        </div>
      ) : questions.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-12 text-center">
          <CheckCircle className="mx-auto h-10 w-10 text-green-400" />
          <p className="mt-3 text-sm font-medium text-gray-700">没有待审核的题目</p>
          <p className="mt-1 text-xs text-gray-500">所有题目已审核完毕</p>
        </div>
      ) : (
        <>
          <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50">
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500">
                    ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500">
                    题干预览
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500">
                    题型
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500">
                    难度
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500">
                    知识点
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500">
                    操作
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {questions.map((q) => (
                  <tr key={q.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <span className="text-xs font-mono text-gray-500">
                        {q.canonical_id}
                      </span>
                    </td>
                    <td className="max-w-xs px-4 py-3">
                      <p className="truncate text-sm text-gray-900">
                        {q.stem.length > 80
                          ? q.stem.slice(0, 80) + '...'
                          : q.stem}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
                        {TYPE_LABELS[q.question_type] || q.question_type}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-xs text-yellow-600">
                        {'★'.repeat(q.difficulty)}{'☆'.repeat(5 - q.difficulty)}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {(q.knowledge_points ?? []).slice(0, 2).map((kp, i) => (
                          <span
                            key={i}
                            className="truncate rounded bg-indigo-50 px-1.5 py-0.5 text-xs text-indigo-600 max-w-[120px]"
                            title={kp}
                          >
                            {kp.split('/').pop()}
                          </span>
                        ))}
                        {(q.knowledge_points ?? []).length > 2 && (
                          <span className="text-xs text-gray-400">
                            +{(q.knowledge_points ?? []).length - 2}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => router.push(`/questions/${q.id}`)}
                          className="rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                          title="查看详情"
                        >
                          <Eye className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => handleReject(q.id)}
                          className="rounded-lg border border-red-200 px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
                          title="驳回"
                        >
                          <XCircle className="mr-1 inline h-3 w-3" />
                          驳回
                        </button>
                        <button
                          onClick={() => handleApprove(q.id)}
                          className="rounded-lg bg-green-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-green-700"
                          title="通过"
                        >
                          <CheckCircle className="mr-1 inline h-3 w-3" />
                          通过
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-gray-500">
                第 {page + 1} / {totalPages} 页，共 {total} 条
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                  className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                >
                  上一页
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={page >= totalPages - 1}
                  className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                >
                  下一页
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
