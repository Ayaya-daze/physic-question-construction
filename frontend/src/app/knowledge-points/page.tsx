'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertCircle, Merge, RefreshCw, Save } from 'lucide-react';
import {
  getFileKnowledgePoints,
  mergeFileKnowledgePoints,
  rebuildFileKnowledgePoints,
  renameFileKnowledgePoint,
  type FileKnowledgePoint,
} from '@/lib/api';

export default function KnowledgePointsPage() {
  const [items, setItems] = useState<FileKnowledgePoint[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [sourceId, setSourceId] = useState('');
  const [targetId, setTargetId] = useState('');
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const applyItems = (next: FileKnowledgePoint[]) => {
    setItems(next);
    setNames(Object.fromEntries(next.map((item) => [item.knowledge_point_id, item.name])));
  };

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      applyItems(await getFileKnowledgePoints());
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取知识点失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const rebuild = async () => {
    setWorking(true);
    setError(null);
    try {
      applyItems(await rebuildFileKnowledgePoints());
    } catch (err) {
      setError(err instanceof Error ? err.message : '重建知识点失败');
    } finally {
      setWorking(false);
    }
  };

  const saveName = async (item: FileKnowledgePoint) => {
    const name = names[item.knowledge_point_id]?.trim();
    if (!name || name === item.name) return;
    setWorking(true);
    setError(null);
    try {
      const updated = await renameFileKnowledgePoint(item.knowledge_point_id, name);
      applyItems(items.map((current) => (
        current.knowledge_point_id === updated.knowledge_point_id ? updated : current
      )));
    } catch (err) {
      setError(err instanceof Error ? err.message : '重命名失败');
    } finally {
      setWorking(false);
    }
  };

  const merge = async () => {
    if (!sourceId || !targetId || sourceId === targetId) {
      setError('请选择两个不同的知识点');
      return;
    }
    setWorking(true);
    setError(null);
    try {
      applyItems(await mergeFileKnowledgePoints(sourceId, targetId));
      setSourceId('');
      setTargetId('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '合并失败');
    } finally {
      setWorking(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-950">知识点</h1>
          <p className="mt-1 text-sm text-gray-500">
            {items.length} 个知识点，全部从正式题目 metadata 派生
          </p>
        </div>
        <button
          type="button"
          onClick={rebuild}
          disabled={working}
          className="inline-flex items-center gap-2 rounded border border-gray-300 px-3 py-2 text-sm font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${working ? 'animate-spin' : ''}`} />
          重建
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-2 border-l-2 border-red-400 pl-3 text-sm text-red-700">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {items.length > 1 && (
        <section className="border-y border-gray-200 py-4">
          <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
            <select
              value={sourceId}
              onChange={(event) => setSourceId(event.target.value)}
              className="rounded border border-gray-300 px-3 py-2 text-sm"
            >
              <option value="">被合并知识点</option>
              {items.map((item) => (
                <option key={item.knowledge_point_id} value={item.knowledge_point_id}>
                  {item.name}
                </option>
              ))}
            </select>
            <select
              value={targetId}
              onChange={(event) => setTargetId(event.target.value)}
              className="rounded border border-gray-300 px-3 py-2 text-sm"
            >
              <option value="">保留知识点</option>
              {items.map((item) => (
                <option key={item.knowledge_point_id} value={item.knowledge_point_id}>
                  {item.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={merge}
              disabled={working}
              className="inline-flex items-center justify-center gap-2 rounded bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
            >
              <Merge className="h-4 w-4" />
              合并
            </button>
          </div>
        </section>
      )}

      <div className="overflow-hidden rounded border border-gray-200 bg-white">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500">名称</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500">别名</th>
              <th className="w-28 px-4 py-3 text-right text-xs font-semibold text-gray-500">题目数</th>
              <th className="w-32 px-4 py-3 text-right text-xs font-semibold text-gray-500">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading && (
              <tr>
                <td colSpan={4} className="px-4 py-12 text-center text-sm text-gray-500">读取中</td>
              </tr>
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-12 text-center text-sm text-gray-500">
                  当前题库还没有知识点 metadata
                </td>
              </tr>
            )}
            {!loading && items.map((item) => (
              <tr key={item.knowledge_point_id}>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <input
                      value={names[item.knowledge_point_id] || ''}
                      onChange={(event) => setNames((current) => ({
                        ...current,
                        [item.knowledge_point_id]: event.target.value,
                      }))}
                      className="min-w-0 flex-1 rounded border border-transparent px-2 py-1.5 text-sm font-medium text-gray-900 hover:border-gray-300 focus:border-blue-500 focus:outline-none"
                    />
                    <button
                      type="button"
                      title="保存名称"
                      onClick={() => saveName(item)}
                      disabled={working || names[item.knowledge_point_id] === item.name}
                      className="rounded p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-900 disabled:opacity-30"
                    >
                      <Save className="h-4 w-4" />
                    </button>
                  </div>
                  <p className="px-2 font-mono text-xs text-gray-400">{item.knowledge_point_id}</p>
                </td>
                <td className="px-4 py-3 text-sm text-gray-600">
                  {item.aliases.length ? item.aliases.join('、') : '无'}
                </td>
                <td className="px-4 py-3 text-right text-sm font-medium text-gray-900">
                  {item.count}
                </td>
                <td className="px-4 py-3 text-right">
                  <Link
                    href={`/questions?knowledge_point_id=${encodeURIComponent(item.knowledge_point_id)}`}
                    className="text-sm font-medium text-blue-700 hover:text-blue-900"
                  >
                    查看题目
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
