'use client';

import { useCallback, useState } from 'react';
import { FileText, Upload, X } from 'lucide-react';

const ACCEPTED_TYPES: Record<string, string> = {
  '.pdf': 'PDF 文档',
  '.md': 'Markdown',
  '.markdown': 'Markdown',
  '.docx': 'Word 文档',
  '.doc': 'Word 文档',
  '.json': '结构化题目',
  '.tex': 'LaTeX 文档',
  '.latex': 'LaTeX 文档',
  '.png': '图片',
  '.jpg': '图片',
  '.jpeg': '图片',
  '.tiff': '图片',
  '.tif': '图片',
  '.bmp': '图片',
  '.webp': '图片',
};

const TYPE_ICONS: Record<string, string> = {
  pdf: '📄',
  markdown: '📝',
  docx: '📃',
  json: '{}',
  tex: '📐',
  image: '🖼️',
};

interface FileItem {
  file: File;
  id: string;
}

interface Props {
  onUpload: (files: File[]) => void;
  uploading: boolean;
}

export default function FileUploader({ onUpload, uploading }: Props) {
  const [files, setFiles] = useState<FileItem[]>([]);
  const [dragOver, setDragOver] = useState(false);

  const addFiles = useCallback((newFiles: FileList | File[]) => {
    const items = Array.from(newFiles)
      .filter((f) => {
        const ext = '.' + f.name.split('.').pop()?.toLowerCase();
        return ext in ACCEPTED_TYPES;
      })
      .map((f) => ({ file: f, id: `${f.name}-${f.size}-${Date.now()}` }));
    setFiles((prev) => [...prev, ...items]);
  }, []);

  const removeFile = useCallback((id: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== id));
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (e.dataTransfer.files.length > 0) {
        addFiles(e.dataTransfer.files);
      }
    },
    [addFiles]
  );

  const handleSubmit = () => {
    if (files.length === 0) return;
    onUpload(files.map((f) => f.file));
  };

  const fileTypeLabel = (filename: string) => {
    const ext = '.' + filename.split('.').pop()?.toLowerCase();
    return ACCEPTED_TYPES[ext] || '未知';
  };

  const typeCategory = (filename: string) => {
    const ext = '.' + filename.split('.').pop()?.toLowerCase();
    if (ext === '.pdf') return 'pdf';
    if (ext === '.md' || ext === '.markdown') return 'markdown';
    if (ext === '.docx' || ext === '.doc') return 'docx';
    if (ext === '.json') return 'json';
    if (ext === '.tex' || ext === '.latex') return 'tex';
    if (['.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp', '.webp'].includes(ext)) return 'image';
    return 'unknown';
  };

  return (
    <div className="space-y-4">
      {/* Drop Zone */}
      <div
        className={`relative rounded-xl border-2 border-dashed p-10 text-center transition-colors ${
          dragOver
            ? 'border-blue-400 bg-blue-50'
            : 'border-gray-300 bg-gray-50 hover:border-gray-400'
        }`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
      >
        <input
          type="file"
          multiple
          accept=".pdf,.md,.markdown,.docx,.doc,.json,.tex,.latex,.png,.jpg,.jpeg,.tiff,.tif,.bmp,.webp"
          className="absolute inset-0 cursor-pointer opacity-0"
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files);
            e.target.value = '';
          }}
        />
        <div className="space-y-3">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-blue-100">
            <Upload className="h-8 w-8 text-blue-600" />
          </div>
          <div>
            <p className="text-base font-medium text-gray-700">
              拖拽文件到此处，或点击选择文件
            </p>
            <p className="mt-1 text-sm text-gray-500">
              支持 PDF、Markdown、Word、LaTeX、结构化 JSON、图片（PNG/JPG）
            </p>
          </div>
        </div>
      </div>

      {/* File List */}
      {files.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-gray-700">
              已选择 {files.length} 个文件
            </h3>
            <button
              onClick={() => setFiles([])}
              className="text-xs text-gray-500 hover:text-gray-700"
            >
              清空全部
            </button>
          </div>
          <ul className="space-y-2">
            {files.map((item) => (
              <li
                key={item.id}
                className="flex items-center gap-3 rounded-lg border border-gray-200 bg-white px-4 py-3"
              >
                <span className="text-xl">
                  {TYPE_ICONS[typeCategory(item.file.name)] || '📎'}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-gray-900">
                    {item.file.name}
                  </p>
                  <p className="text-xs text-gray-500">
                    {fileTypeLabel(item.file.name)} · {(item.file.size / 1024).toFixed(1)} KB
                  </p>
                </div>
                <button
                  onClick={() => removeFile(item.id)}
                  className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                  disabled={uploading}
                >
                  <X className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Submit Button */}
      {files.length > 0 && (
        <button
          onClick={handleSubmit}
          disabled={uploading}
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {uploading ? (
            <>
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              上传中...
            </>
          ) : (
            <>
              <Upload className="h-4 w-4" />
              提交后台导入任务（{files.length} 个文件）
            </>
          )}
        </button>
      )}
    </div>
  );
}
