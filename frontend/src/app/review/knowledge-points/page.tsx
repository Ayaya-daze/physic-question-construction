'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  ArrowLeft,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  GitBranch,
  GitMerge,
  Search,
  XCircle,
} from 'lucide-react';
import {
  getKPCandidates,
  approveKPCandidate,
  rejectKPCandidate,
  mergeKPCandidate,
  type KnowledgePointCandidateRead,
} from '@/lib/api';

const SOURCE_LABELS: Record<string, string> = {
  llm: 'LLM',
  import: '导入',
  human: '人工',
  merged: '合并',
};

const SOURCE_BADGE_COLORS: Record<string, string> = {
  llm: 'bg-purple-100 text-purple-700',
  import: 'bg-blue-100 text-blue-700',
  human: 'bg-teal-100 text-teal-700',
  merged: 'bg-orange-100 text-orange-700',
};

export default function KnowledgePointCandidatesPage() {
  const router = useRouter();
  const [candidates, setCandidates] = useState<KnowledgePointCandidateRead[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [mergeOpenId, setMergeOpenId] = useState<string | null>(null);
  const [mergeSearch, setMergeSearch] = useState<string>('');
  const [mergeResults, setMergeResults] = useState<{ id: number; path: string; name: string }[]>([]);
  const [mergeLoading, setMergeLoading] = useState(false);
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pageSize = 50;

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getKPCandidates({
        skip: page * pageSize,
        limit: pageSize,
        status: 'pending',
      });
      setCandidates(res.items ?? []);
      setTotal(res.total ?? 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleApprove = async (candidateId: string, canonicalName: string) => {
    try {
      const result = await approveKPCandidate(candidateId);
      setActionMsg(`"${canonicalName}" 已通过，创建知识点 #${result.id}`);
      await fetchData();
      setTimeout(() => setActionMsg(null), 3000);
    } catch (err) {
      setActionMsg(`操作失败: ${err instanceof Error ? err.message : '未知错误'}`);
    }
  };

  const handleReject = async (candidateId: string, canonicalName: string) => {
    const reason = prompt('驳回原因（可选）：');
    try {
      await rejectKPCandidate(candidateId, reason || undefined);
      setActionMsg(`"${canonicalName}" 已驳回`);
      await fetchData();
      setTimeout(() => setActionMsg(null), 3000);
    } catch (err) {
      setActionMsg(`操作失败: ${err instanceof Error ? err.message : '未知错误'}`);
    }
  };

  const handleMergeSearch = async (query: string) => {
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }
    if (!query.trim()) {
      setMergeResults([]);
      return;
    }
    searchTimeoutRef.current = setTimeout(async () => {
      setMergeLoading(true);
      try {
        const res = await fetch(`/api/knowledge-points?search=${encodeURIComponent(query)}`);
        if (res.ok) {
          const data = await res.json();
          setMergeResults(Array.isArray(data) ? data.slice(0, 10) : []);
        } else {
          setMergeResults([]);
        }
      } catch {
        setMergeResults([]);
      } finally {
        setMergeLoading(false);
      }
    }, 300);
  };

  const handleMerge = async (candidateId: string, targetKpId: number, canonicalName: string) => {
    try {
      const result = await mergeKPCandidate(candidateId, targetKpId);
      setActionMsg(`"${canonicalName}" 已合并到 "${result.merged_into_kp_name}"`);
      setMergeOpenId(null);
      setMergeSearch('');
      setMergeResults([]);
      await fetchData();
      setTimeout(() => setActionMsg(null), 3000);
    } catch (err) {
      setActionMsg(`合并失败: ${err instanceof Error ? err.message : '未知错误'}`);
    }
  };

  const toggleExpand = (candidateId: string) => {
    setExpandedId((prev) => (prev === candidateId ? null : candidateId));
  };

  const confidenceBadge = (confidence: number) => {
    if (confidence > 0.8) {
      return 'bg-green-100 text-green-700';
    }
    if (confidence > 0.5) {
      return 'bg-yellow-100 text-yellow-700';
    }
    return 'bg-red-100 text-red-700';
  };

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => router.push('/review')}
          className="rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
        >
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">知识点候选审核</h1>
          <p className="mt-1 text-sm text-gray-500">
            审核由 LLM 或外部资料识别到的候选知识点，通过后加入知识体系
          </p>
        </div>
      </div>

      {/* Action message */}
      {actionMsg && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
          <p className="text-sm text-blue-700">{actionMsg}</p>
        </div>
      )}

      {/* Loading skeleton */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="h-20 animate-pulse rounded-lg bg-gray-100"
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
      ) : candidates.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-12 text-center">
          <GitBranch className="mx-auto h-10 w-10 text-green-400" />
          <p className="mt-3 text-sm font-medium text-gray-700">暂无待审核的知识点候选</p>
          <p className="mt-1 text-xs text-gray-500">所有候选知识点已审核完毕</p>
        </div>
      ) : (
        <>
          <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50">
                  <th className="w-8 px-3 py-3" />
                  <th className="px-3 py-3 text-left text-xs font-semibold text-gray-500">
                    候选名称
                  </th>
                  <th className="px-3 py-3 text-left text-xs font-semibold text-gray-500">
                    定义
                  </th>
                  <th className="px-3 py-3 text-left text-xs font-semibold text-gray-500">
                    置信度
                  </th>
                  <th className="px-3 py-3 text-left text-xs font-semibold text-gray-500">
                    父路径建议
                  </th>
                  <th className="px-3 py-3 text-left text-xs font-semibold text-gray-500">
                    来源
                  </th>
                  <th className="px-3 py-3 text-right text-xs font-semibold text-gray-500">
                    操作
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {candidates.map((c) => {
                  const isExpanded = expandedId === c.candidate_id;
                  const isMerging = mergeOpenId === c.candidate_id;

                  return (
                    <tr key={c.candidate_id}>
                      <td colSpan={7} className="p-0">
                        <div className={isExpanded ? 'bg-blue-50/30' : ''}>
                          {/* Main row */}
                          <div className="flex items-stretch hover:bg-gray-50">
                            <button
                              onClick={() => toggleExpand(c.candidate_id)}
                              className="flex w-8 items-center justify-center text-gray-400 hover:text-gray-600"
                            >
                              {isExpanded ? (
                                <ChevronDown className="h-4 w-4" />
                              ) : (
                                <ChevronRight className="h-4 w-4" />
                              )}
                            </button>
                            <div className="flex flex-1 items-center py-3 pr-3">
                              <div className="w-[18%] px-3">
                                <span className="text-sm font-semibold text-gray-900">
                                  {c.canonical_name}
                                </span>
                              </div>
                              <div className="w-[22%] px-3">
                                <p className="truncate text-sm text-gray-600">
                                  {c.definition
                                    ? c.definition.length > 100
                                      ? c.definition.slice(0, 100) + '...'
                                      : c.definition
                                    : (
                                      <span className="italic text-gray-400">
                                        无定义
                                      </span>
                                    )}
                                </p>
                              </div>
                              <div className="w-[10%] px-3">
                                <span
                                  className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${confidenceBadge(c.confidence)}`}
                                >
                                  {(c.confidence * 100).toFixed(0)}%
                                </span>
                              </div>
                              <div className="w-[18%] px-3">
                                <span className="truncate text-xs text-gray-500">
                                  {c.suggested_parent_path || '—'}
                                </span>
                              </div>
                              <div className="w-[10%] px-3">
                                <span
                                  className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${
                                    SOURCE_BADGE_COLORS[c.source] || 'bg-gray-100 text-gray-600'
                                  }`}
                                >
                                  {SOURCE_LABELS[c.source] || c.source}
                                </span>
                              </div>
                              {/* Source question link */}
                              <div className="w-[8%] px-3">
                                {c.source_question ? (
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      router.push(`/questions/${c.source_question!.id}`);
                                    }}
                                    className="truncate text-xs text-blue-600 hover:text-blue-800 hover:underline"
                                  >
                                    #{c.source_question.canonical_id}
                                  </button>
                                ) : (
                                  <span className="text-xs text-gray-400">—</span>
                                )}
                              </div>
                              {/* Actions */}
                              <div className="flex w-[16%] items-center justify-end gap-2 px-3">
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setMergeOpenId(mergeOpenId === c.candidate_id ? null : c.candidate_id);
                                    setMergeSearch('');
                                    setMergeResults([]);
                                  }}
                                  className="rounded-lg border border-gray-200 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-100"
                                  title="合并到已有知识点"
                                >
                                  <GitMerge className="mr-1 inline h-3 w-3" />
                                  合并
                                </button>
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleReject(c.candidate_id, c.canonical_name);
                                  }}
                                  className="rounded-lg border border-red-200 px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
                                  title="驳回"
                                >
                                  <XCircle className="mr-1 inline h-3 w-3" />
                                  驳回
                                </button>
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleApprove(c.candidate_id, c.canonical_name);
                                  }}
                                  className="rounded-lg bg-green-600 px-2 py-1 text-xs font-medium text-white hover:bg-green-700"
                                  title="通过"
                                >
                                  <CheckCircle className="mr-1 inline h-3 w-3" />
                                  通过
                                </button>
                              </div>
                            </div>
                          </div>

                          {/* Expanded detail */}
                          {isExpanded && (
                            <div className="border-t border-blue-100 bg-blue-50/50 px-11 py-4">
                              <div className="grid gap-4 md:grid-cols-2">
                                <div>
                                  <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                                    完整定义
                                  </h4>
                                  <p className="mt-1 text-sm text-gray-700 whitespace-pre-wrap">
                                    {c.definition || '（未提供定义）'}
                                  </p>
                                </div>
                                <div>
                                  <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                                    来源文本片段
                                  </h4>
                                  <p className="mt-1 text-sm text-gray-700 whitespace-pre-wrap italic">
                                    {c.source_text_snippet || '（无来源文本）'}
                                  </p>
                                </div>
                              </div>
                              <div className="mt-3 grid gap-4 md:grid-cols-3">
                                <div>
                                  <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                                    候选 ID
                                  </h4>
                                  <p className="text-xs font-mono text-gray-500">
                                    {c.candidate_id}
                                  </p>
                                </div>
                                <div>
                                  <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                                    审核者
                                  </h4>
                                  <p className="text-xs text-gray-500">
                                    {c.reviewer || '—'}
                                  </p>
                                </div>
                                {c.review_note && (
                                  <div>
                                    <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                                      审核备注
                                    </h4>
                                    <p className="text-xs text-gray-500">
                                      {c.review_note}
                                    </p>
                                  </div>
                                )}
                              </div>
                            </div>
                          )}

                          {/* Merge panel */}
                          {isMerging && (
                            <div className="border-t border-orange-100 bg-orange-50/50 px-11 py-3">
                              <p className="mb-2 text-xs font-medium text-gray-700">
                                搜索要合并到的已有知识点：
                              </p>
                              <div className="flex items-center gap-2">
                                <div className="relative flex-1">
                                  <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400" />
                                  <input
                                    type="text"
                                    value={mergeSearch}
                                    onChange={(e) => {
                                      setMergeSearch(e.target.value);
                                      handleMergeSearch(e.target.value);
                                    }}
                                    placeholder="输入知识点名称搜索..."
                                    className="w-full rounded border border-gray-300 py-1.5 pl-8 pr-3 text-xs focus:border-orange-500 focus:outline-none focus:ring-1 focus:ring-orange-500"
                                  />
                                </div>
                                <button
                                  onClick={() => {
                                    setMergeOpenId(null);
                                    setMergeSearch('');
                                    setMergeResults([]);
                                  }}
                                  className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-500 hover:bg-white"
                                >
                                  取消
                                </button>
                              </div>
                              {/* Merge search results */}
                              {mergeLoading && (
                                <p className="mt-2 text-xs text-gray-400">搜索中...</p>
                              )}
                              {mergeResults.length > 0 && (
                                <div className="mt-2 max-h-40 space-y-1 overflow-y-auto rounded border border-gray-200 bg-white p-1">
                                  {mergeResults.map((kp) => (
                                    <button
                                      key={kp.id}
                                      onClick={() =>
                                        handleMerge(c.candidate_id, kp.id, c.canonical_name)
                                      }
                                      className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-xs hover:bg-orange-50"
                                    >
                                      <span className="font-medium text-gray-700">
                                        {kp.name}
                                      </span>
                                      <span className="text-gray-400">
                                        <GitMerge className="h-3 w-3" />
                                      </span>
                                    </button>
                                  ))}
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
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
