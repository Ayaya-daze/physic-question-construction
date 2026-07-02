'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  Clock,
  Download,
  Edit3,
  FileText,
  Hash,
  Loader2,
  Lock,
  MinusCircle,
  PanelRight,
  Plus,
  RefreshCw,
  Search,
  Star,
  Trash2,
  X,
} from 'lucide-react';
import type {
  AssemblyConstraints,
  AssemblyResult,
  ExportJobRead,
  PaperDetail,
  PaperQuestionRead,
  QuestionList,
} from '@/lib/api';
import {
  addQuestionToPaper,
  assemblePaper,
  deletePaper,
  exportPaper,
  getExportDownloadUrl,
  getExportJob,
  getKnowledgePointTree,
  getPaper,
  getQuestions,
  removeQuestionFromPaper,
  replaceQuestionInPaper,
  updatePaper,
  validatePaper,
} from '@/lib/api';

// --- Constants ---

const paperStatusConfig: Record<string, { label: string; className: string }> = {
  draft: { label: '草稿', className: 'bg-gray-100 text-gray-700' },
  assembling: { label: '组题中', className: 'bg-yellow-100 text-yellow-700' },
  assembled: { label: '已组题', className: 'bg-blue-100 text-blue-700' },
  exported: { label: '已导出', className: 'bg-green-100 text-green-700' },
  archived: { label: '已归档', className: 'bg-gray-100 text-gray-500' },
};

const questionTypeLabels: Record<string, string> = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  true_false: '判断题',
  fill_blank: '填空题',
  short_answer: '简答题',
  calculation: '计算题',
  experiment: '实验题',
};

const exportStatusConfig: Record<string, { label: string; className: string }> = {
  pending: { label: '等待中', className: 'bg-gray-100 text-gray-600' },
  running: { label: '处理中', className: 'bg-yellow-100 text-yellow-700' },
  succeeded: { label: '已完成', className: 'bg-green-100 text-green-700' },
  partial: { label: '部分完成', className: 'bg-yellow-100 text-yellow-700' },
  failed: { label: '失败', className: 'bg-red-100 text-red-700' },
};

function DifficultyStars({ difficulty }: { difficulty: number }) {
  return (
    <span className="inline-flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((star) =>
        star <= difficulty ? (
          <Star key={star} className="h-3.5 w-3.5 fill-yellow-400 text-yellow-400" />
        ) : (
          <Star key={star} className="h-3.5 w-3.5 text-gray-300" />
        )
      )}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const cfg = paperStatusConfig[status] ?? {
    label: status,
    className: 'bg-gray-100 text-gray-700',
  };
  return (
    <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${cfg.className}`}>
      {cfg.label}
    </span>
  );
}

// Separate component for each question row to properly use useState
function QuestionRow({
  pq,
  sectionMap,
  actionLoading,
  onReplace,
  onRemove,
}: {
  pq: PaperQuestionRead;
  sectionMap: Map<number, { id: number; name: string; question_type: string; count: number; score_each: number; order_index: number; constraints_json?: Record<string, unknown>; question_count?: number }>;
  actionLoading: string | null;
  onReplace: (paperQuestionId: number, newCanonicalId: string) => Promise<void>;
  onRemove: (paperQuestionId: number) => Promise<void>;
}) {
  const [replaceInput, setReplaceInput] = useState('');
  const [showReplace, setShowReplace] = useState(false);

  const q = pq.question;
  const section = pq.paper_section_id ? sectionMap.get(pq.paper_section_id) : undefined;

  const truncate = (text: string, max: number) =>
    text.length > max ? text.slice(0, max) + '...' : text;

  return (
    <tr className="hover:bg-gray-50 transition-colors">
      <td className="px-4 py-3 text-sm text-gray-500">{pq.order_index}</td>
      <td className="px-4 py-3">
        <span className="text-xs font-mono text-gray-600">{q?.canonical_id || '—'}</span>
        {pq.is_locked && (
          <span className="ml-1.5 inline-flex items-center gap-0.5 text-xs text-blue-600" title="已锁定">
            <Lock className="h-3 w-3" />
          </span>
        )}
      </td>
      <td className="px-4 py-3 max-w-xs">
        <div className="text-sm text-gray-900">{q ? truncate(q.stem, 80) : '（题目已删除）'}</div>
        {section && (
          <span className="mt-0.5 inline-block text-xs text-gray-400">{section.name}</span>
        )}
      </td>
      <td className="px-4 py-3">
        {q && (
          <span className="inline-flex rounded-md bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
            {questionTypeLabels[q.question_type] || q.question_type}
          </span>
        )}
      </td>
      <td className="px-4 py-3">
        {q && <DifficultyStars difficulty={q.difficulty} />}
      </td>
      <td className="px-4 py-3 text-sm text-gray-600">{pq.score ?? section?.score_each ?? '—'}</td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-1 flex-wrap">
          {showReplace ? (
            <div className="flex items-center gap-1">
              <input
                type="text"
                value={replaceInput}
                onChange={(e) => setReplaceInput(e.target.value)}
                placeholder="题目 canonical_id"
                className="w-40 rounded border border-gray-300 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    onReplace(pq.id, replaceInput);
                    setShowReplace(false);
                    setReplaceInput('');
                  }
                  if (e.key === 'Escape') {
                    setShowReplace(false);
                    setReplaceInput('');
                  }
                }}
              />
              <button
                onClick={() => {
                  onReplace(pq.id, replaceInput);
                  setShowReplace(false);
                  setReplaceInput('');
                }}
                disabled={!replaceInput.trim() || actionLoading === `replace-${pq.id}`}
                className="p-1 text-green-600 hover:bg-green-50 rounded transition-colors"
              >
                {actionLoading === `replace-${pq.id}` ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
              </button>
              <button
                onClick={() => { setShowReplace(false); setReplaceInput(''); }}
                className="p-1 text-gray-400 hover:bg-gray-100 rounded transition-colors"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <>
              {!pq.is_locked && (
                <button
                  onClick={() => setShowReplace(true)}
                  className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors"
                  title="替换"
                >
                  <RefreshCw className="h-4 w-4" />
                </button>
              )}
              {!pq.is_locked && (
                <button
                  onClick={() => onRemove(pq.id)}
                  disabled={actionLoading === `remove-${pq.id}`}
                  className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors"
                  title="移除"
                >
                  {actionLoading === `remove-${pq.id}` ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <MinusCircle className="h-4 w-4" />
                  )}
                </button>
              )}
              {pq.is_locked && (
                <span className="text-xs text-gray-400 italic">已锁定</span>
              )}
            </>
          )}
        </div>
      </td>
    </tr>
  );
}

// --- Main Component ---

export default function PaperWorkbenchPage() {
  const params = useParams<{ paperId: string }>();
  const router = useRouter();
  const paperId = params.paperId;

  // Paper state
  const [paper, setPaper] = useState<PaperDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);

  // Editable title
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [editTitle, setEditTitle] = useState('');

  // Panel visibility
  const [showAddPanel, setShowAddPanel] = useState(false);
  const [showAssemblyPanel, setShowAssemblyPanel] = useState(false);
  const [showValidationPanel, setShowValidationPanel] = useState(false);
  const [showExportPanel, setShowExportPanel] = useState(false);

  // Add question state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<QuestionList[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [addTargetSectionId, setAddTargetSectionId] = useState<number | undefined>(undefined);
  const [addingCanonicalId, setAddingCanonicalId] = useState<string | null>(null);

  // Assembly state
  const [knowledgePoints, setKnowledgePoints] = useState<{ id: number; name: string; path: string }[]>([]);
  const [selectedKPs, setSelectedKPs] = useState<string[]>([]);
  const [difficultyMin, setDifficultyMin] = useState('');
  const [difficultyMax, setDifficultyMax] = useState('');
  const [assemblyResult, setAssemblyResult] = useState<AssemblyResult | null>(null);
  const [assembling, setAssembling] = useState(false);

  // Validation state
  const [validationReport, setValidationReport] = useState<Record<string, unknown> | null>(null);
  const [validating, setValidating] = useState(false);

  // Export state
  const [exportFormat, setExportFormat] = useState('tex_pdf');
  const [exportJob, setExportJob] = useState<ExportJobRead | null>(null);
  const [exporting, setExporting] = useState(false);
  const [pollingExport, setPollingExport] = useState(false);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Cleanup polling interval on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, []);

  // --- Fetch paper detail ---
  const fetchPaper = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getPaper(paperId);
      setPaper(data);
      setEditTitle(data.title);
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取试卷详情失败');
    } finally {
      setLoading(false);
    }
  }, [paperId]);

  useEffect(() => {
    fetchPaper();
  }, [fetchPaper]);

  // --- Fetch knowledge points for assembly ---
  const fetchKnowledgePoints = useCallback(async () => {
    try {
      const kps = await getKnowledgePointTree();
      // Flatten tree into list with paths for the selector UI
      const flat: { id: number; name: string; path: string }[] = [];
      function walk(items: typeof kps, parentPath: string) {
        for (const item of items) {
          const path = item.path || (parentPath ? `${parentPath}/${item.name}` : item.name);
          flat.push({ id: item.id, name: item.name, path });
          if (item.children && item.children.length > 0) {
            walk(item.children, path);
          }
        }
      }
      walk(kps, '');
      setKnowledgePoints(flat);
    } catch {
      setPageError('加载知识点失败，筛选功能不可用');
    }
  }, []);

  // --- Title editing ---
  const handleSaveTitle = async () => {
    if (!paper || !editTitle.trim()) return;
    setActionLoading('title');
    try {
      const updated = await updatePaper(paperId, { title: editTitle.trim() });
      setPaper((prev) => (prev ? { ...prev, title: updated.title } : prev));
      setIsEditingTitle(false);
    } catch (err) {
      setPageError(`更新标题失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setActionLoading(null);
    }
  };

  // --- Delete paper ---
  const handleDelete = async () => {
    if (!paper) return;
    if (!window.confirm(`确定要删除试卷「${paper.title}」吗？此操作不可撤销。`)) return;
    setActionLoading('delete');
    try {
      await deletePaper(paperId);
      router.push('/papers');
    } catch (err) {
      setPageError(`删除失败: ${err instanceof Error ? err.message : '未知错误'}`);
      setActionLoading(null);
    }
  };

  // --- Add question ---
  const handleSearchQuestions = async () => {
    if (!searchQuery.trim()) return;
    setSearchLoading(true);
    try {
      const result = await getQuestions({ q: searchQuery, limit: '10', status: 'approved' });
      setSearchResults(result.items ?? []);
    } catch (err) {
      setSearchResults([]);
      setPageError(`搜索失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setSearchLoading(false);
    }
  };

  const handleAddQuestion = async (canonicalId: string) => {
    setAddingCanonicalId(canonicalId);
    try {
      const pq = await addQuestionToPaper(paperId, canonicalId, addTargetSectionId);
      // Refresh the whole paper to get updated sections question_count and questions list
      await fetchPaper();
    } catch (err) {
      setPageError(`添加失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setAddingCanonicalId(null);
    }
  };

  const handleRemoveQuestion = async (paperQuestionId: number) => {
    setActionLoading(`remove-${paperQuestionId}`);
    try {
      await removeQuestionFromPaper(paperId, paperQuestionId);
      await fetchPaper();
    } catch (err) {
      setPageError(`移除失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setActionLoading(null);
    }
  };

  const handleReplaceQuestion = async (paperQuestionId: number, newCanonicalId: string) => {
    if (!newCanonicalId.trim()) return;
    setActionLoading(`replace-${paperQuestionId}`);
    try {
      await replaceQuestionInPaper(paperId, paperQuestionId, newCanonicalId.trim());
      await fetchPaper();
    } catch (err) {
      setPageError(`替换失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setActionLoading(null);
    }
  };

  // --- Assembly ---
  const handleAssemble = async () => {
    if (!paper) return;
    setAssembling(true);
    setAssemblyResult(null);
    try {
      const constraints: AssemblyConstraints = {};
      if (selectedKPs.length > 0) constraints.knowledge_point_paths = selectedKPs;
      if (difficultyMin) constraints.difficulty_min = Number(difficultyMin);
      if (difficultyMax) constraints.difficulty_max = Number(difficultyMax);

      // Lock existing questions (section config is read from DB, not sent separately)
      const existingIds = (paper.questions ?? []).map((q) => q.question?.canonical_id).filter(Boolean) as string[];
      if (existingIds.length > 0) {
        constraints.selected_question_ids = existingIds;
        constraints.lock_selected_questions = true;
      }

      const result = await assemblePaper(paperId, constraints);
      setAssemblyResult(result);
      await fetchPaper();
    } catch (err) {
      setPageError(`组题失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setAssembling(false);
    }
  };

  // --- Validation ---
  const handleValidate = async () => {
    setValidating(true);
    setValidationReport(null);
    try {
      const report = await validatePaper(paperId);
      setValidationReport(report);
    } catch (err) {
      setPageError(`校验失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setValidating(false);
    }
  };

  // --- Export ---
  const handleExport = async () => {
    setExporting(true);
    setExportJob(null);
    try {
      const job = await exportPaper(paperId, { format: exportFormat });
      setExportJob(job);
      if (job.status === 'running' || job.status === 'pending') {
        pollExportStatus(job.export_id);
      }
    } catch (err) {
      setPageError(`导出失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setExporting(false);
    }
  };

  const pollExportStatus = async (exportId: string) => {
    setPollingExport(true);
    // Clear any existing poll first
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    const maxPolls = 30;
    let polls = 0;
    pollIntervalRef.current = setInterval(async () => {
      polls++;
      try {
        const job = await getExportJob(paperId, exportId);
        setExportJob(job);
        if (job.status === 'succeeded' || job.status === 'partial' || job.status === 'failed' || polls >= maxPolls) {
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
          }
          setPollingExport(false);
        }
      } catch {
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
        }
        setPollingExport(false);
      }
    }, 2000);
  };

  // --- Format helpers ---
  const formatDate = (iso: string) => {
    return new Date(iso).toLocaleString('zh-CN');
  };

  // --- Loading State ---
  if (loading) {
    return (
      <div className="space-y-6">
        <Link href="/papers" className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors">
          <ArrowLeft className="h-4 w-4" />返回组卷列表
        </Link>
        <div className="rounded-xl border border-gray-200 bg-white p-6 animate-pulse space-y-4">
          <div className="h-8 w-64 rounded bg-gray-200" />
          <div className="h-4 w-48 rounded bg-gray-200" />
          <div className="h-32 rounded bg-gray-100" />
          <div className="h-32 rounded bg-gray-100" />
        </div>
      </div>
    );
  }

  // --- Error State ---
  if (error) {
    return (
      <div className="space-y-4">
        <Link href="/papers" className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors">
          <ArrowLeft className="h-4 w-4" />返回组卷列表
        </Link>
        <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4">
          <AlertCircle className="h-5 w-5 flex-shrink-0 text-red-500 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-red-800">加载失败</p>
            <p className="mt-1 text-sm text-red-600">{error}</p>
            <button onClick={fetchPaper} className="mt-3 rounded-md bg-red-100 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-200 transition-colors">
              重试
            </button>
          </div>
        </div>
      </div>
    );
  }

  // --- Not Found ---
  if (!paper) {
    return (
      <div className="space-y-4">
        <Link href="/papers" className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors">
          <ArrowLeft className="h-4 w-4" />返回组卷列表
        </Link>
        <div className="text-center py-16">
          <FileText className="mx-auto h-12 w-12 text-gray-300" />
          <p className="mt-3 text-sm font-medium text-gray-500">试卷不存在</p>
          <p className="mt-1 text-sm text-gray-400">该试卷可能已被删除</p>
        </div>
      </div>
    );
  }

  // Build a section-id map for quick lookup
  const sectionMap = new Map(paper.sections.map((s) => [s.id, s]));

  return (
    <div className="space-y-6">
      {/* Back Link */}
      <Link href="/papers" className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors">
        <ArrowLeft className="h-4 w-4" />返回组卷列表
      </Link>

      {/* Inline error banner */}
      {pageError && (
        <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4">
          <AlertCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-red-500" />
          <div className="flex-1">
            <p className="text-sm font-medium text-red-800">操作失败</p>
            <p className="mt-1 text-sm text-red-600">{pageError}</p>
          </div>
          <button onClick={() => setPageError(null)} className="p-1 text-red-400 hover:text-red-600 rounded transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* ========== Header ========== */}
      <div className="rounded-xl border border-gray-200 bg-white p-6">
        <div className="flex flex-wrap items-start gap-4 justify-between">
          <div className="flex-1 min-w-0">
            {isEditingTitle ? (
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleSaveTitle();
                    if (e.key === 'Escape') setIsEditingTitle(false);
                  }}
                  className="text-2xl font-bold text-gray-900 bg-transparent border-b-2 border-blue-500 focus:outline-none px-1 py-0.5 w-full max-w-lg"
                  autoFocus
                />
                <button onClick={handleSaveTitle} disabled={actionLoading === 'title'} className="p-1.5 text-blue-600 hover:bg-blue-50 rounded transition-colors">
                  {actionLoading === 'title' ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                </button>
                <button onClick={() => setIsEditingTitle(false)} className="p-1.5 text-gray-400 hover:bg-gray-100 rounded transition-colors">
                  <X className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-bold text-gray-900 truncate">{paper.title}</h1>
                <button onClick={() => { setIsEditingTitle(true); setEditTitle(paper.title); }} className="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors">
                  <Edit3 className="h-4 w-4" />
                </button>
              </div>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <StatusBadge status={paper.status} />
              {paper.grade && (
                <span className="text-sm text-gray-600">年级：{paper.grade}</span>
              )}
              {paper.total_score && (
                <span className="text-sm text-gray-600">总分：{paper.total_score}</span>
              )}
              {paper.duration_minutes && (
                <span className="text-sm text-gray-600">时长：{paper.duration_minutes} 分钟</span>
              )}
              <span className="text-sm text-gray-500 flex items-center gap-1">
                <Hash className="h-3.5 w-3.5" />
                {paper.paper_id}
              </span>
            </div>
            {paper.description && (
              <p className="mt-2 text-sm text-gray-500">{paper.description}</p>
            )}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              onClick={() => setShowExportPanel(!showExportPanel)}
              className="inline-flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-green-700 transition-colors shadow-sm"
            >
              <Download className="h-4 w-4" />
              导出
            </button>
            <button
              onClick={handleDelete}
              disabled={actionLoading === 'delete'}
              className="inline-flex items-center gap-2 rounded-lg border border-red-300 px-3 py-2.5 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 transition-colors"
            >
              {actionLoading === 'delete' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
            </button>
          </div>
        </div>
      </div>

      {/* ========== Sections Table ========== */}
      {paper.sections.length > 0 && (
        <section>
          <h2 className="mb-3 text-lg font-semibold text-gray-900">试卷结构</h2>
          <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">大题</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">题型</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">目标题数</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">已选题数</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">每题分数</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">小计</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {paper.sections.map((section) => (
                  <tr key={section.id}>
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">{section.name}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {questionTypeLabels[section.question_type] || section.question_type}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">{section.count}</td>
                    <td className="px-4 py-3">
                      <span className={`text-sm font-medium ${(section.question_count || 0) >= section.count ? 'text-green-600' : (section.question_count || 0) > 0 ? 'text-yellow-600' : 'text-red-500'}`}>
                        {section.question_count || 0}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">{section.score_each}</td>
                    <td className="px-4 py-3 text-sm font-medium text-gray-700">
                      {(section.question_count || 0) * section.score_each}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ========== Questions List ========== */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold text-gray-900">
            试题列表 <span className="text-sm font-normal text-gray-400">({(paper.questions ?? []).length} 题)</span>
          </h2>
          <button
            onClick={() => {
              setShowAddPanel(!showAddPanel);
              if (!showAddPanel) setShowAssemblyPanel(false);
            }}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
          >
            <Plus className="h-4 w-4" />
            添加题目
          </button>
        </div>

        {(paper.questions ?? []).length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-300 bg-white px-6 py-12 text-center">
            <ClipboardList className="mx-auto h-10 w-10 text-gray-300" />
            <p className="mt-3 text-sm font-medium text-gray-500">暂未添加题目</p>
            <p className="mt-1 text-sm text-gray-400">点击「添加题目」手动选题，或使用「智能组题」自动生成</p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500 w-12">#</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500 w-32">编号</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">题干</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">题型</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">难度</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">分数</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {(paper.questions ?? []).map((pq) => (
                  <QuestionRow
                    key={pq.id}
                    pq={pq}
                    sectionMap={sectionMap}
                    actionLoading={actionLoading}
                    onReplace={handleReplaceQuestion}
                    onRemove={handleRemoveQuestion}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ========== Add Question Panel ========== */}
      {showAddPanel && (
        <section className="rounded-xl border border-blue-200 bg-blue-50/30 p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
              <PanelRight className="h-5 w-5 text-blue-600" />
              添加题目
            </h3>
            <button onClick={() => setShowAddPanel(false)} className="p-1 text-gray-400 hover:text-gray-600 rounded transition-colors">
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Search */}
          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleSearchQuestions(); }}
                placeholder="搜索题干关键词..."
                className="w-full rounded-lg border border-gray-300 py-2.5 pl-10 pr-4 text-sm placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <button
              onClick={handleSearchQuestions}
              disabled={searchLoading}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {searchLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              搜索
            </button>
          </div>

          {/* Section target selector */}
          {paper.sections.length > 0 && (
            <div className="mt-3">
              <label className="block text-xs font-medium text-gray-600 mb-1">添加到哪个大题（可选）</label>
              <select
                value={addTargetSectionId ?? ''}
                onChange={(e) => setAddTargetSectionId(e.target.value ? Number(e.target.value) : undefined)}
                className="rounded-lg border border-gray-300 py-2 px-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="">自动匹配</option>
                {paper.sections.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({questionTypeLabels[s.question_type] || s.question_type}, {(s.question_count || 0)}/{s.count})
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Search Results */}
          {searchResults.length > 0 && (
            <div className="mt-4 space-y-2">
              <p className="text-xs text-gray-500">搜索结果 ({searchResults.length} 题)</p>
              {searchResults.map((q) => (
                <div key={q.id} className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-4 py-3">
                  <div className="flex-1 min-w-0 mr-4">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono text-gray-500">{q.canonical_id}</span>
                      <span className="inline-flex rounded-md bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
                        {questionTypeLabels[q.question_type] || q.question_type}
                      </span>
                      <DifficultyStars difficulty={q.difficulty} />
                      {q.grade && <span className="text-xs text-gray-400">{q.grade}</span>}
                    </div>
                    <p className="mt-1 text-sm text-gray-800 line-clamp-1">{q.stem}</p>
                  </div>
                  <button
                    onClick={() => handleAddQuestion(q.canonical_id)}
                    disabled={addingCanonicalId === q.canonical_id}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors flex-shrink-0"
                  >
                    {addingCanonicalId === q.canonical_id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Plus className="h-3.5 w-3.5" />
                    )}
                    添加
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* ========== Assembly Panel ========== */}
      <section className="rounded-xl border border-gray-200 bg-white p-5">
        <button
          onClick={() => {
            setShowAssemblyPanel(!showAssemblyPanel);
            if (!showAssemblyPanel) {
              fetchKnowledgePoints();
              setAssemblyResult(null);
            }
          }}
          className="flex items-center justify-between w-full text-left"
        >
          <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <RefreshCw className="h-5 w-5 text-purple-600" />
            智能组题
          </h3>
          {showAssemblyPanel ? <ChevronDown className="h-5 w-5 text-gray-400" /> : <ChevronRight className="h-5 w-5 text-gray-400" />}
        </button>

        {showAssemblyPanel && (
          <div className="mt-4 space-y-4">
            <p className="text-sm text-gray-500">
              根据试卷结构自动匹配题库中的题目。已锁定的题目不会被替换。
            </p>

            {/* Knowledge point selector */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">知识点范围（可选，留空则不限制）</label>
              <div className="flex flex-wrap gap-2 max-h-40 overflow-y-auto border border-gray-200 rounded-lg p-3">
                {knowledgePoints.length === 0 ? (
                  <p className="text-sm text-gray-400">加载知识点中...</p>
                ) : (
                  knowledgePoints.map((kp) => {
                    const selected = selectedKPs.includes(kp.path);
                    return (
                      <button
                        key={kp.path}
                        onClick={() => {
                          setSelectedKPs((prev) =>
                            selected ? prev.filter((p) => p !== kp.path) : [...prev, kp.path]
                          );
                        }}
                        className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
                          selected
                            ? 'border-purple-300 bg-purple-50 text-purple-700'
                            : 'border-gray-200 bg-white text-gray-600 hover:border-purple-200 hover:bg-purple-50/50'
                        }`}
                      >
                        {kp.name}
                      </button>
                    );
                  })
                )}
              </div>
              {selectedKPs.length > 0 && (
                <p className="mt-1 text-xs text-gray-400">已选 {selectedKPs.length} 个知识点</p>
              )}
            </div>

            {/* Difficulty range */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">最低难度</label>
                <input
                  type="number"
                  min={1}
                  max={5}
                  value={difficultyMin}
                  onChange={(e) => setDifficultyMin(e.target.value)}
                  placeholder="1"
                  className="w-full rounded-lg border border-gray-300 py-2 px-3 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">最高难度</label>
                <input
                  type="number"
                  min={1}
                  max={5}
                  value={difficultyMax}
                  onChange={(e) => setDifficultyMax(e.target.value)}
                  placeholder="5"
                  className="w-full rounded-lg border border-gray-300 py-2 px-3 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                />
              </div>
            </div>

            {/* Assemble button */}
            <button
              onClick={handleAssemble}
              disabled={assembling}
              className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50 transition-colors shadow-sm"
            >
              {assembling ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              开始组题
            </button>

            {/* Assembly result */}
            {assemblyResult && (
              <div className="rounded-lg border border-purple-200 bg-purple-50 p-4">
                <h4 className="text-sm font-semibold text-purple-900">组题结果</h4>
                <div className="mt-2 space-y-2 text-sm text-purple-800">
                  <p>匹配题数: {(assemblyResult.paper_questions ?? []).length}</p>
                  <p>候选池大小: {assemblyResult.candidate_pool_size}</p>
                  {assemblyResult.unfilled_sections && assemblyResult.unfilled_sections.length > 0 && (
                    <div>
                      <p className="font-medium text-red-700">未填满的题位:</p>
                      {assemblyResult.unfilled_sections.map((uf, i) => (
                        <p key={i} className="text-red-600">
                          {uf.section_name}: 需要 {uf.needed} 题，已填 {uf.filled} 题
                        </p>
                      ))}
                    </div>
                  )}
                  {(!assemblyResult.unfilled_sections || assemblyResult.unfilled_sections.length === 0) && (
                    <p className="text-green-700 flex items-center gap-1">
                      <CheckCircle2 className="h-4 w-4" />
                      所有题位已填满
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      {/* ========== Validation Panel ========== */}
      <section className="rounded-xl border border-gray-200 bg-white p-5">
        <button
          onClick={() => { setShowValidationPanel(!showValidationPanel); setValidationReport(null); }}
          className="flex items-center justify-between w-full text-left"
        >
          <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <CheckCircle2 className="h-5 w-5 text-orange-600" />
            校验试卷
          </h3>
          {showValidationPanel ? <ChevronDown className="h-5 w-5 text-gray-400" /> : <ChevronRight className="h-5 w-5 text-gray-400" />}
        </button>

        {showValidationPanel && (
          <div className="mt-4 space-y-4">
            <p className="text-sm text-gray-500">校验试卷结构完整性、题目分布、分数设置等。</p>
            <button
              onClick={handleValidate}
              disabled={validating}
              className="inline-flex items-center gap-2 rounded-lg bg-orange-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-orange-700 disabled:opacity-50 transition-colors shadow-sm"
            >
              {validating ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              校验试卷
            </button>

            {validationReport && (
              <div className="rounded-lg border border-orange-200 bg-orange-50 p-4">
                <h4 className="text-sm font-semibold text-orange-900">校验报告</h4>
                <div className="mt-2 space-y-2">
                  {Object.entries(validationReport).map(([key, value]) => (
                    <div key={key} className="flex items-start gap-2 text-sm">
                      <span className="font-medium text-orange-800 flex-shrink-0">{key}:</span>
                      <span className="text-orange-700">
                        {typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)}
                      </span>
                    </div>
                  ))}
                  {Object.keys(validationReport).length === 0 && (
                    <p className="text-sm text-green-700 flex items-center gap-1">
                      <CheckCircle2 className="h-4 w-4" />校验通过，无问题
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      {/* ========== Export Panel ========== */}
      {showExportPanel && (
        <section className="rounded-xl border border-green-200 bg-green-50/30 p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
              <Download className="h-5 w-5 text-green-600" />
              导出试卷
            </h3>
            <button onClick={() => setShowExportPanel(false)} className="p-1 text-gray-400 hover:text-gray-600 rounded transition-colors">
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="space-y-4">
            {/* Format selector */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">导出格式</label>
              <div className="flex gap-3">
                <button
                  onClick={() => setExportFormat('tex_pdf')}
                  className={`rounded-lg border px-4 py-2.5 text-sm font-medium transition-colors ${
                    exportFormat === 'tex_pdf'
                      ? 'border-green-300 bg-green-50 text-green-700'
                      : 'border-gray-200 bg-white text-gray-600 hover:border-green-200'
                  }`}
                >
                  TeX + PDF
                </button>
                <button
                  onClick={() => setExportFormat('tex_only')}
                  className={`rounded-lg border px-4 py-2.5 text-sm font-medium transition-colors ${
                    exportFormat === 'tex_only'
                      ? 'border-green-300 bg-green-50 text-green-700'
                      : 'border-gray-200 bg-white text-gray-600 hover:border-green-200'
                  }`}
                >
                  仅 TeX
                </button>
              </div>
            </div>

            <button
              onClick={handleExport}
              disabled={exporting || pollingExport}
              className="inline-flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50 transition-colors shadow-sm"
            >
              {(exporting || pollingExport) ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FileText className="h-4 w-4" />
              )}
              导出试卷
            </button>

            {/* Export job status */}
            {exportJob && (
              <div className="rounded-lg border border-green-200 bg-white p-4">
                <div className="flex items-center gap-2 mb-2">
                  <h4 className="text-sm font-semibold text-gray-900">导出任务</h4>
                  <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${exportStatusConfig[exportJob.status]?.className || 'bg-gray-100 text-gray-600'}`}>
                    {exportStatusConfig[exportJob.status]?.label || exportJob.status}
                  </span>
                </div>
                <div className="space-y-2 text-sm text-gray-600">
                  <p>格式: {exportJob.format} / 变体: {exportJob.variant}</p>
                  <p>创建时间: {formatDate(exportJob.created_at)}</p>
                  {exportJob.finished_at && <p>完成时间: {formatDate(exportJob.finished_at)}</p>}
                  {exportJob.error_message && (
                    <p className="text-red-600">错误: {exportJob.error_message}</p>
                  )}
                </div>

                {/* Build logs */}
                {(exportJob.questions_build_log_preview || exportJob.answers_build_log_preview) && (
                  <div className="mt-3 space-y-2">
                    {exportJob.questions_build_log_preview && (
                      <details>
                        <summary className="cursor-pointer text-sm text-blue-600 hover:text-blue-800">题目卷构建日志</summary>
                        <pre className="mt-2 rounded bg-gray-50 p-3 text-xs text-gray-700 overflow-x-auto whitespace-pre-wrap">{exportJob.questions_build_log_preview}</pre>
                      </details>
                    )}
                    {exportJob.answers_build_log_preview && (
                      <details>
                        <summary className="cursor-pointer text-sm text-blue-600 hover:text-blue-800">答案卷构建日志</summary>
                        <pre className="mt-2 rounded bg-gray-50 p-3 text-xs text-gray-700 overflow-x-auto whitespace-pre-wrap">{exportJob.answers_build_log_preview}</pre>
                      </details>
                    )}
                  </div>
                )}

                {/* Legacy build log fallback */}
                {!exportJob.questions_build_log_preview && !exportJob.answers_build_log_preview && exportJob.build_log_preview && (
                  <details className="mt-3">
                    <summary className="cursor-pointer text-sm text-blue-600 hover:text-blue-800">构建日志</summary>
                    <pre className="mt-2 rounded bg-gray-50 p-3 text-xs text-gray-700 overflow-x-auto whitespace-pre-wrap">{exportJob.build_log_preview}</pre>
                  </details>
                )}

                {/* Download links */}
                {(exportJob.status === 'succeeded' || exportJob.status === 'partial') && (
                  <div className="mt-4 space-y-3">
                    {/* Question paper downloads */}
                    <div>
                      <p className="text-xs font-semibold text-gray-500 uppercase mb-1.5">📝 题目卷</p>
                      <div className="flex flex-wrap gap-2">
                        {exportJob.questions_tex_path && (
                          <a
                            href={getExportDownloadUrl(paperId, exportJob.export_id, 'questions-tex')}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
                          >
                            <Download className="h-4 w-4" />
                            questions.tex
                          </a>
                        )}
                        {exportJob.questions_pdf_path && (
                          <a
                            href={getExportDownloadUrl(paperId, exportJob.export_id, 'questions-pdf')}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-2 text-sm font-medium text-white hover:bg-green-700 transition-colors"
                          >
                            <Download className="h-4 w-4" />
                            questions.pdf
                          </a>
                        )}
                        {exportJob.questions_build_log_preview && (
                          <a
                            href={getExportDownloadUrl(paperId, exportJob.export_id, 'questions-log')}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50 transition-colors"
                          >
                            <FileText className="h-4 w-4" />
                            构建日志
                          </a>
                        )}
                      </div>
                    </div>

                    {/* Answer paper downloads */}
                    <div>
                      <p className="text-xs font-semibold text-gray-500 uppercase mb-1.5">📋 答案卷</p>
                      <div className="flex flex-wrap gap-2">
                        {exportJob.answers_tex_path && (
                          <a
                            href={getExportDownloadUrl(paperId, exportJob.export_id, 'answers-tex')}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
                          >
                            <Download className="h-4 w-4" />
                            answers.tex
                          </a>
                        )}
                        {exportJob.answers_pdf_path && (
                          <a
                            href={getExportDownloadUrl(paperId, exportJob.export_id, 'answers-pdf')}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-2 text-sm font-medium text-white hover:bg-green-700 transition-colors"
                          >
                            <Download className="h-4 w-4" />
                            answers.pdf
                          </a>
                        )}
                        {exportJob.answers_build_log_preview && (
                          <a
                            href={getExportDownloadUrl(paperId, exportJob.export_id, 'answers-log')}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50 transition-colors"
                          >
                            <FileText className="h-4 w-4" />
                            构建日志
                          </a>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </section>
      )}

      {/* ========== Footer: Timestamps ========== */}
      <div className="flex items-center gap-4 text-xs text-gray-400 border-t border-gray-200 pt-4">
        <span className="flex items-center gap-1">
          <Clock className="h-3.5 w-3.5" />
          创建: {formatDate(paper.created_at)}
        </span>
        <span className="flex items-center gap-1">
          <Clock className="h-3.5 w-3.5" />
          更新: {formatDate(paper.updated_at)}
        </span>
      </div>
    </div>
  );
}
