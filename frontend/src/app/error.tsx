'use client';

import { AlertCircle, RefreshCw } from 'lucide-react';
import { useEffect } from 'react';

export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('Unhandled application error:', error);
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="mx-auto max-w-md rounded-xl border border-red-200 bg-white p-8 text-center shadow-sm">
        <AlertCircle className="mx-auto h-12 w-12 text-red-400" />
        <h1 className="mt-4 text-lg font-semibold text-gray-900">应用发生错误</h1>
        <p className="mt-2 text-sm text-gray-600">
          {error.message || '发生了意外错误，请重试。'}
        </p>
        {error.digest && (
          <p className="mt-1 text-xs text-gray-400 font-mono">Error ID: {error.digest}</p>
        )}
        <button
          onClick={reset}
          className="mt-6 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
        >
          <RefreshCw className="h-4 w-4" />
          重试
        </button>
      </div>
    </div>
  );
}
