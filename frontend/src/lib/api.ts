// ============================================================
// API Client — Physics Question Bank
// ============================================================

// --- TypeScript interfaces matching backend Pydantic schemas ---

export interface ChoiceOption {
  option_label: string;
  content: string;
  is_correct?: boolean;
  order_index?: number;
}

export interface Answer {
  answer_type: string;
  content: string;
  normalized_content?: string;
  unit?: string;
  significant_figures?: number;
}

export interface SolutionStep {
  step_order: number;
  content: string;
  formula?: string;
  explanation?: string;
}

export interface KnowledgePoint {
  id: number;
  name: string;
  description?: string;
  parent_id?: number;
  path?: string;
  level?: number;
  question_count?: number;
  children?: KnowledgePoint[];
}

export interface KnowledgePointRef {
  path: string;
  weight?: number;
  is_primary?: boolean;
}

export interface Tag {
  id: number;
  name: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  skip: number;
  limit: number;
}

export interface Question {
  id: number;
  canonical_id: string;
  question_type: string;
  stem: string;
  options?: ChoiceOption[];
  choice_options?: ChoiceOption[];
  answers: Answer[];
  answer_type?: string;
  difficulty: number;
  grade?: string;
  solution_steps: SolutionStep[];
  knowledge_points: KnowledgePointRef[];
  tags: string[];
  status: string;
  source_document?: string;
  source_document_id?: string;
  source_page?: number;
  created_at: string;
  updated_at: string;
}

export interface QuestionList {
  id: number;
  canonical_id: string;
  question_type: string;
  stem: string;
  difficulty: number;
  grade?: string;
  status: string;
  created_at: string;
  updated_at: string;
  tags: string[];
  knowledge_points: string[];
}

export interface QuestionCreate {
  question_type: string;
  stem: string;
  options?: ChoiceOption[];
  answers: Answer[];
  difficulty: number;
  grade?: string;
  solution_steps: SolutionStep[];
  knowledge_points?: KnowledgePointRef[];
  tags?: string[];
  source_document_id?: string;
  source_page?: number;
  knowledge_point_mode?: string;  // "candidate" (default), "strict", "force_create"
}

export interface FileQuestionAsset {
  filename: string;
  path: string;
  url: string;
  mime_hint: string;
}

export interface FileQuestionSummary {
  question_id: string;
  title: string;
  preview: string;
  metadata: Record<string, unknown>;
  assets: FileQuestionAsset[];
  updated_at: string;
  size_bytes: number;
  indexed: boolean;
  score?: number | null;
}

export interface FileQuestionDetail extends FileQuestionSummary {
  question_body: string;
  answer_body: string;
  question_format: 'markdown' | 'latex' | 'text';
  answer_format?: 'markdown' | 'latex' | 'text' | null;
  content_hash: string;
}

export interface FileQuestionCreate {
  question_id?: string;
  question_body: string;
  answer_body?: string;
  question_format?: 'markdown' | 'latex' | 'text';
  answer_format?: 'markdown' | 'latex' | 'text';
  metadata?: Record<string, unknown>;
  overwrite?: boolean;
}

export interface FileImportConfig {
  enabled: boolean;
  configured: boolean;
  provider: string;
  model: string;
  supports_vision: boolean;
  vision_configured: boolean;
  supported_extensions: string[];
}

export interface FileQuestionImportItem extends FileQuestionSummary {
  source_filename: string;
}

export interface FileQuestionImportResponse {
  imported: FileQuestionImportItem[];
  errors: Array<{ filename: string; error: string }>;
  warnings: string[];
  llm_assist_requested: boolean;
  llm_assist_used: boolean;
  question_count: number;
}

export interface FileQuestionStats {
  total: number;
  indexed: number;
  with_assets: number;
  human_review_needed: number;
}

export interface FileImportJobSource {
  filename?: string | null;
  source_type?: string | null;
  relative_path?: string | null;
  size_bytes?: number | null;
  process: boolean;
  status: string;
  error?: string | null;
}

export interface FileImportJob {
  job_id: string;
  status: string;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  use_llm_assist: boolean;
  overwrite: boolean;
  source_files: FileImportJobSource[];
  total_files: number;
  processed_files: number;
  current_file?: string | null;
  created_question_ids: string[];
  imported_count: number;
  errors: Array<{ filename: string; error: string }>;
  warnings: string[];
  llm_used: boolean;
  index_rebuilt: boolean;
}

// --- Helper: fetch wrapper ---

async function apiFetch<T>(url: string, options?: RequestInit, timeoutMs = 30_000): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  const res = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
    signal: controller.signal,
  }).finally(() => clearTimeout(timeoutId));

  if (!res.ok) {
    let errorMessage = `API error ${res.status}: ${res.statusText}`;
    try {
      const errorBody = await res.json();
      if (errorBody.detail) {
        errorMessage = typeof errorBody.detail === 'string' ? errorBody.detail : JSON.stringify(errorBody.detail);
      } else if (errorBody.message) {
        errorMessage = errorBody.message;
      }
    } catch {
      // ignore parse errors on error responses
    }
    throw new Error(errorMessage);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  // 防御：非 JSON 响应 → 抛出错误 → 各页面显示错误态而非崩溃
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`服务器返回了无效数据 (${url})`);
  }
}

// --- Exported API functions ---

export async function getQuestions(
  params: Record<string, string>
): Promise<PaginatedResponse<QuestionList>> {
  const searchParams = new URLSearchParams(params);
  const query = searchParams.toString();
  return apiFetch<PaginatedResponse<QuestionList>>(`/api/questions?${query}`);
}

export async function getQuestion(id: number | string): Promise<Question> {
  return apiFetch<Question>(`/api/questions/${id}`);
}


export async function getFileQuestions(params: {
  q?: string;
  skip?: number;
  limit?: number;
} = {}): Promise<PaginatedResponse<FileQuestionSummary>> {
  const searchParams = new URLSearchParams();
  if (params.q) searchParams.set('q', params.q);
  if (params.skip !== undefined) searchParams.set('skip', String(params.skip));
  if (params.limit !== undefined) searchParams.set('limit', String(params.limit));
  const query = searchParams.toString();
  return apiFetch<PaginatedResponse<FileQuestionSummary>>(`/api/file-questions${query ? `?${query}` : ''}`);
}

export async function getFileQuestion(id: string): Promise<FileQuestionDetail> {
  return apiFetch<FileQuestionDetail>(`/api/file-questions/${id}`);
}

export async function getFileQuestionStats(): Promise<FileQuestionStats> {
  return apiFetch<FileQuestionStats>('/api/file-questions/stats');
}

export async function updateFileQuestion(id: string, data: { question_body?: string; answer_body?: string }): Promise<FileQuestionDetail> {
  return apiFetch<FileQuestionDetail>(`/api/file-questions/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}


export async function getFileImportConfig(): Promise<FileImportConfig> {
  return apiFetch<FileImportConfig>('/api/file-questions/import/config');
}

export async function importFileQuestions(
  files: File[],
  options: { use_llm_assist?: boolean; overwrite?: boolean } = {}
): Promise<FileQuestionImportResponse> {
  const formData = new FormData();
  files.forEach((file) => formData.append('files', file));
  formData.append('use_llm_assist', String(Boolean(options.use_llm_assist)));
  formData.append('overwrite', String(Boolean(options.overwrite)));

  const res = await fetch('/api/file-questions/import', {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Import error ${res.status}`);
  }
  return res.json();
}

export async function createFileImportJob(
  files: File[],
  options: { use_llm_assist?: boolean; overwrite?: boolean } = {}
): Promise<FileImportJob> {
  const formData = new FormData();
  files.forEach((file) => formData.append('files', file));
  formData.append('use_llm_assist', String(Boolean(options.use_llm_assist)));
  formData.append('overwrite', String(Boolean(options.overwrite)));

  const res = await fetch('/api/file-questions/import/jobs', {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Import job error ${res.status}`);
  }
  return res.json();
}

export async function getFileImportJob(jobId: string): Promise<FileImportJob> {
  return apiFetch<FileImportJob>(`/api/file-questions/import/jobs/${jobId}`);
}

export async function listFileImportJobs(limit = 20): Promise<FileImportJob[]> {
  return apiFetch<FileImportJob[]>(`/api/file-questions/import/jobs?limit=${limit}`);
}


export async function exportFilePaper(data: {
  title: string;
  question_ids?: string[];
  search_query?: string;
  question_count?: number;
}): Promise<{
  status: string;
  export_id: string;
  title: string;
  question_count: number;
  question_ids: string[];
  // New split outputs
  question_tex_url: string;
  question_pdf_url?: string | null;
  question_build_log_url?: string | null;
  answer_tex_url: string;
  answer_pdf_url?: string | null;
  answer_build_log_url?: string | null;
  // Legacy compat
  tex_path: string;
  tex_url: string;
  pdf_path?: string | null;
  pdf_url?: string | null;
  build_log_path?: string | null;
  build_log_url?: string | null;
}> {
  return apiFetch('/api/file-questions/papers/export', {
    method: 'POST',
    body: JSON.stringify(data),
  }, 240_000);
}


export async function getKnowledgePoints(
  parentId?: number
): Promise<KnowledgePoint[]> {
  const params = parentId !== undefined ? `?parent_id=${parentId}` : '';
  return apiFetch<KnowledgePoint[]>(`/api/knowledge-points${params}`);
}

export async function getKnowledgePointTree(): Promise<KnowledgePoint[]> {
  return apiFetch<KnowledgePoint[]>('/api/knowledge-points/tree');
}


export async function getQuestionContent(id: number | string): Promise<{
  canonical_id: string;
  content: string;
  source: string;
}> {
  return apiFetch<{ canonical_id: string; content: string; source: string }>(`/api/questions/${id}/content`);
}


export interface SourceDocumentRead {
  document_id: string;
  title?: string;
  source_type: string;
  original_filename?: string;
  book_title?: string;
  publisher?: string;
  author?: string;
  year?: number;
  page_count?: number;
  copyright_note?: string;
  created_at: string;
}

export interface ExtractionJobRead {
  job_id: string;
  job_type: string;
  status: string;
  tool_name?: string;
  model_name?: string;
  error_message?: string;
  candidate_count: number;
  created_at: string;
  finished_at?: string;
}

export interface ExtractionJobDetail extends ExtractionJobRead {
  input_snapshot?: Record<string, unknown>;
  output_snapshot?: Record<string, unknown>;
}

export interface MediaAssetRead {
  asset_id: string;
  asset_type: string;
  file_path: string;
  mime_type?: string;
  width?: number;
  height?: number;
  page_number?: number;
  region?: number[];
}

export interface SourceDocumentDetail extends SourceDocumentRead {
  extraction_jobs: ExtractionJobRead[];
  media_assets: MediaAssetRead[];
}

export interface CandidateQuestion {
  index: number;
  question: Record<string, unknown>;
  confidence: number;
  warnings: string[];
  needs_review: string[];
  source_page?: number;
  source_region?: number[];
  asset_refs: string[];
}

export interface UploadResponse {
  document_id: string;
  original_filename: string;
  source_type: string;
  jobs: ExtractionJobRead[];
}

export interface MultiUploadResponse {
  documents: UploadResponse[];
  errors: Array<{ filename: string; error: string }>;
}

// Upload files (multipart/form-data)


export async function getSourceDocument(docId: string): Promise<SourceDocumentDetail> {
  return apiFetch<SourceDocumentDetail>(`/api/uploads/documents/${docId}`);
}


export async function processDocument(docId: string): Promise<ExtractionJobRead> {
  return apiFetch<ExtractionJobRead>(`/api/uploads/documents/${docId}/process`, { method: 'POST' });
}

// Extraction Jobs
export async function getExtractionJob(jobId: string): Promise<ExtractionJobDetail> {
  return apiFetch<ExtractionJobDetail>(`/api/uploads/jobs/${jobId}`);
}

export async function getJobCandidates(jobId: string): Promise<CandidateQuestion[]> {
  return apiFetch<CandidateQuestion[]>(`/api/uploads/jobs/${jobId}/candidates`);
}


export async function approveCandidate(
  jobId: string,
  index: number
): Promise<{ id: number; canonical_id: string; status: string }> {
  return apiFetch<{ id: number; canonical_id: string; status: string }>(
    `/api/uploads/jobs/${jobId}/candidates/${index}/approve`,
    { method: 'POST' }
  );
}

export async function rejectCandidate(
  jobId: string,
  index: number
): Promise<{ detail: string }> {
  return apiFetch<{ detail: string }>(
    `/api/uploads/jobs/${jobId}/candidates/${index}`,
    { method: 'DELETE' }
  );
}

export async function batchApproveCandidates(
  jobId: string,
  indices: number[]
): Promise<{ approved: Array<{ index: number; canonical_id: string }>; errors: Array<{ index: number; error: string }> }> {
  return apiFetch<{
    approved: Array<{ index: number; canonical_id: string }>;
    errors: Array<{ index: number; error: string }>;
  }>(`/api/uploads/jobs/${jobId}/candidates/batch-approve`, {
    method: 'POST',
    body: JSON.stringify({ indices }),
  });
}

export async function getPageImageUrl(docId: string, page: number): Promise<string> {
  return `/media/pages/${docId}/page_${String(page).padStart(3, '0')}.png`;
}

// ============================================================
// Review API
// ============================================================

export interface PendingQuestion {
  id: number;
  canonical_id: string;
  question_type: string;
  stem: string;
  difficulty: number;
  grade?: string;
  status: string;
  knowledge_points: string[];
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface PendingReviewResponse {
  items: PendingQuestion[];
  total: number;
  skip: number;
  limit: number;
}

export async function getPendingReviews(params?: {
  skip?: number;
  limit?: number;
  q?: string;
}): Promise<PendingReviewResponse> {
  const searchParams = new URLSearchParams();
  if (params?.skip !== undefined) searchParams.set('skip', String(params.skip));
  if (params?.limit !== undefined) searchParams.set('limit', String(params.limit));
  if (params?.q) searchParams.set('q', params.q);
  const query = searchParams.toString();
  return apiFetch<PendingReviewResponse>(`/api/review/pending${query ? `?${query}` : ''}`);
}

export async function getPendingCount(): Promise<{ count: number }> {
  return apiFetch<{ count: number }>('/api/review/pending/count');
}

export async function approveQuestion(questionId: number): Promise<{ id: number; canonical_id: string; status: string }> {
  return apiFetch<{ id: number; canonical_id: string; status: string }>(
    `/api/review/${questionId}/approve`,
    { method: 'POST' }
  );
}

export async function rejectQuestion(questionId: number, reason?: string): Promise<{ id: number; canonical_id: string; status: string }> {
  const query = reason ? `?reason=${encodeURIComponent(reason)}` : '';
  return apiFetch<{ id: number; canonical_id: string; status: string }>(
    `/api/review/${questionId}/reject${query}`,
    { method: 'POST' }
  );
}

// ============================================================
// Knowledge Point Candidate API
// ============================================================

export interface KnowledgePointCandidateRead {
  id: number;
  candidate_id: string;
  canonical_name: string;
  definition?: string;
  suggested_parent_path?: string;
  suggested_parent_id?: number;
  confidence: number;
  source: string;
  status: string;
  source_question_id?: number;
  source_document_id?: number;
  source_text_snippet?: string;
  reviewer?: string;
  review_note?: string;
  merged_into_kp_id?: number;
  created_at: string;
  updated_at: string;
  source_question?: {
    id: number;
    canonical_id: string;
    stem: string;
    question_type: string;
  };
}

export interface KnowledgePointCandidateListResponse {
  items: KnowledgePointCandidateRead[];
  total: number;
  skip: number;
  limit: number;
}

export async function getKPCandidates(params?: {
  q?: string;
  status?: string;
  skip?: number;
  limit?: number;
}): Promise<KnowledgePointCandidateListResponse> {
  const query = new URLSearchParams();
  if (params?.q) query.set('q', params.q);
  if (params?.status) query.set('status', params.status);
  if (params?.skip !== undefined) query.set('skip', String(params.skip));
  if (params?.limit !== undefined) query.set('limit', String(params.limit));
  const qs = query.toString();
  return apiFetch<KnowledgePointCandidateListResponse>(
    `/api/knowledge-point-candidates${qs ? '?' + qs : ''}`
  );
}

export async function approveKPCandidate(
  candidateId: string
): Promise<{ id: number; name: string; path: string; status: string; candidate_id: string }> {
  return apiFetch<{ id: number; name: string; path: string; status: string; candidate_id: string }>(
    `/api/knowledge-point-candidates/${candidateId}/approve`,
    { method: 'POST' }
  );
}

export async function rejectKPCandidate(
  candidateId: string,
  reason?: string
): Promise<{ candidate_id: string; status: string; reason: string }> {
  const query = reason ? `?reason=${encodeURIComponent(reason)}` : '';
  return apiFetch<{ candidate_id: string; status: string; reason: string }>(
    `/api/knowledge-point-candidates/${candidateId}/reject${query}`,
    { method: 'POST' }
  );
}

export async function mergeKPCandidate(
  candidateId: string,
  targetKpId: number
): Promise<{
  candidate_id: string;
  status: string;
  merged_into_kp_id: number;
  merged_into_kp_name: string;
  alias_created: string;
}> {
  return apiFetch<{
    candidate_id: string;
    status: string;
    merged_into_kp_id: number;
    merged_into_kp_name: string;
    alias_created: string;
  }>(`/api/knowledge-point-candidates/${candidateId}/merge`, {
    method: 'POST',
    body: JSON.stringify({ target_kp_id: targetKpId }),
  });
}


export interface PaperSectionRead {
  id: number;
  paper_id: number;
  name: string;
  question_type: string;
  count: number;
  score_each: number;
  order_index: number;
  constraints_json?: Record<string, unknown>;
  question_count?: number;
}

export interface PaperSectionCreate {
  name: string;
  question_type: string;
  count: number;
  score_each: number;
  order_index?: number;
  constraints_json?: Record<string, unknown>;
}

export interface PaperRead {
  paper_id: string;
  title: string;
  description?: string;
  total_score?: number;
  duration_minutes?: number;
  grade?: string;
  difficulty_target?: number;
  generation_mode: string;
  status: string;
  include_answers: boolean;
  constraints_json?: Record<string, unknown>;
  validation_result_json?: Record<string, unknown>;
  sections: PaperSectionRead[];
  question_count: number;
  created_at: string;
  updated_at: string;
}

export interface PaperDetail extends PaperRead {
  questions: PaperQuestionRead[];
}

export interface PaperQuestionRead {
  id: number;
  paper_section_id?: number;
  order_index: number;
  score?: number;
  is_locked: boolean;
  selection_reason?: string;
  source_mode: string;
  question?: {
    id: number;
    canonical_id: string;
    question_type: string;
    stem: string;
    difficulty: number;
    grade?: string;
  };
}

export interface AssemblyConstraints {
  selected_question_ids?: string[];
  lock_selected_questions?: boolean;
  knowledge_point_paths?: string[];
  sections?: PaperSectionCreate[];
  use_llm_assist?: boolean;
  use_semantic_search?: boolean;
  natural_language_requirement?: string;
  difficulty_min?: number;
  difficulty_max?: number;
  exclude_recent_days?: number;
  similarity_threshold?: number;
  tag_filter?: string[];
  include_answers?: boolean;
}

export interface AssemblyResult {
  paper_questions: PaperQuestionRead[];
  unfilled_sections: Array<{ section_name: string; needed: number; filled: number }>;
  candidate_pool_size: number;
  validation_report?: Record<string, unknown>;
}

export interface ExportRequest {
  format?: string;
  variant?: string;
  template_id?: string;
  latex_engine?: string;
}

export interface ExportJobRead {
  export_id: string;
  paper_id?: string;
  format: string;
  variant: string;
  template_id?: string;
  latex_engine?: string;
  status: string;

  // ── Questions paper outputs ──
  questions_tex_path?: string;
  questions_pdf_path?: string;
  questions_build_log_preview?: string;

  // ── Answers paper outputs ──
  answers_tex_path?: string;
  answers_pdf_path?: string;
  answers_build_log_preview?: string;

  // ── Legacy compat fields ──
  tex_path?: string;
  pdf_path?: string;
  build_log_preview?: string;

  assets_dir?: string;
  error_message?: string;
  created_at: string;
  finished_at?: string;
}

// Paper CRUD
export async function createPaper(data: { title: string; description?: string; total_score?: number; duration_minutes?: number; grade?: string; sections?: PaperSectionCreate[]; include_answers?: boolean }): Promise<PaperRead> {
  return apiFetch<PaperRead>('/api/papers/drafts', { method: 'POST', body: JSON.stringify(data) });
}
export async function listPapers(params?: { skip?: number; limit?: number; status?: string }): Promise<{ items: PaperRead[]; total: number; skip: number; limit: number }> {
  const sp = new URLSearchParams();
  if (params?.skip !== undefined) sp.set('skip', String(params.skip));
  if (params?.limit !== undefined) sp.set('limit', String(params.limit));
  if (params?.status) sp.set('status', params.status);
  const qs = sp.toString();
  return apiFetch(`/api/papers${qs ? '?' + qs : ''}`);
}
export async function getPaper(paperId: string): Promise<PaperDetail> {
  return apiFetch<PaperDetail>(`/api/papers/${paperId}`);
}
export async function updatePaper(paperId: string, data: Partial<PaperRead>): Promise<PaperRead> {
  return apiFetch<PaperRead>(`/api/papers/${paperId}`, { method: 'PUT', body: JSON.stringify(data) });
}
export async function deletePaper(paperId: string): Promise<void> {
  return apiFetch<void>(`/api/papers/${paperId}`, { method: 'DELETE' });
}

// Paper questions
export async function addQuestionToPaper(paperId: string, canonicalId: string, sectionId?: number): Promise<PaperQuestionRead> {
  return apiFetch<PaperQuestionRead>(`/api/papers/${paperId}/questions`, { method: 'POST', body: JSON.stringify({ canonical_id: canonicalId, section_id: sectionId }) });
}
export async function removeQuestionFromPaper(paperId: string, paperQuestionId: number): Promise<void> {
  return apiFetch<void>(`/api/papers/${paperId}/questions/${paperQuestionId}`, { method: 'DELETE' });
}
export async function replaceQuestionInPaper(paperId: string, paperQuestionId: number, newCanonicalId: string): Promise<PaperQuestionRead> {
  return apiFetch<PaperQuestionRead>(`/api/papers/${paperId}/questions/${paperQuestionId}/replace`, { method: 'POST', body: JSON.stringify({ canonical_id: newCanonicalId }) });
}

// Assembly + Validate + Export
export async function assemblePaper(paperId: string, constraints: AssemblyConstraints): Promise<AssemblyResult> {
  return apiFetch<AssemblyResult>(`/api/papers/${paperId}/assemble`, { method: 'POST', body: JSON.stringify(constraints) });
}
export async function validatePaper(paperId: string): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/papers/${paperId}/validate`, { method: 'POST' });
}
export async function exportPaper(paperId: string, data?: ExportRequest): Promise<ExportJobRead> {
  return apiFetch<ExportJobRead>(`/api/papers/${paperId}/export`, { method: 'POST', body: JSON.stringify(data || {}) });
}
export async function getExportJob(paperId: string, exportId: string): Promise<ExportJobRead> {
  return apiFetch<ExportJobRead>(`/api/papers/${paperId}/exports/${exportId}`);
}
export type ExportDownloadType =
  | 'questions-pdf' | 'questions-tex' | 'answers-pdf' | 'answers-tex'
  | 'questions-log' | 'answers-log'
  | 'pdf' | 'tex';  // legacy aliases

export function getExportDownloadUrl(paperId: string, exportId: string, type: ExportDownloadType = 'questions-pdf'): string {
  return `/api/papers/${paperId}/exports/${exportId}/download?type=${type}`;
}
