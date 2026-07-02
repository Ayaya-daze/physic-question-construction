'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import {
  ArrowRight,
  BookOpen,
  CheckCircle,
  Clock,
  FileText,
  Image as ImageIcon,
  Upload,
} from 'lucide-react';
import { getFileQuestionStats } from '@/lib/api';

interface StatItem {
  label: string;
  value: number | null;
  icon: React.ComponentType<{ className?: string }>;
  bgColor: string;
  iconColor: string;
  loading: boolean;
}

const quickActions = [
  {
    label: '导入题目',
    description: '上传文件或导入 agent 处理结果',
    href: '/upload',
    icon: Upload,
    color: 'bg-blue-500',
  },
  {
    label: '浏览题库',
    description: '搜索、筛选和管理所有题目',
    href: '/questions',
    icon: BookOpen,
    color: 'bg-green-500',
  },
  {
    label: '文件组卷',
    description: '从题目文件导出题目卷和答案卷',
    href: '/papers/generator',
    icon: FileText,
    color: 'bg-gray-900',
  },
];

function PulsingNumber({ loading, value }: { loading: boolean; value: number | null }) {
  if (loading) {
    return <span className="inline-block h-8 w-12 animate-pulse rounded bg-gray-200" />;
  }
  return <span>{value?.toLocaleString() ?? '—'}</span>;
}

export default function HomePage() {
  const [stats, setStats] = useState<StatItem[]>([
    { label: '题库总数', value: null, icon: BookOpen, bgColor: 'bg-blue-50', iconColor: 'text-blue-600', loading: true },
    { label: '已索引', value: null, icon: CheckCircle, bgColor: 'bg-green-50', iconColor: 'text-green-600', loading: true },
    { label: '含图题目', value: null, icon: ImageIcon, bgColor: 'bg-gray-50', iconColor: 'text-gray-700', loading: true },
    { label: '需复核', value: null, icon: Clock, bgColor: 'bg-yellow-50', iconColor: 'text-yellow-600', loading: true },
  ]);

  useEffect(() => {
    let cancelled = false;

    async function fetchStats() {
      try {
        const fileStats = await getFileQuestionStats();

        if (!cancelled) {
          setStats([
            { label: '题库总数', value: fileStats.total, icon: BookOpen, bgColor: 'bg-blue-50', iconColor: 'text-blue-600', loading: false },
            { label: '已索引', value: fileStats.indexed, icon: CheckCircle, bgColor: 'bg-green-50', iconColor: 'text-green-600', loading: false },
            { label: '含图题目', value: fileStats.with_assets, icon: ImageIcon, bgColor: 'bg-gray-50', iconColor: 'text-gray-700', loading: false },
            { label: '需复核', value: fileStats.human_review_needed, icon: Clock, bgColor: 'bg-yellow-50', iconColor: 'text-yellow-600', loading: false },
          ]);
        }
      } catch {
        // keep defaults on error
      }
    }

    fetchStats();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="space-y-8">
      {/* Welcome Banner */}
      <div className="rounded-2xl bg-gradient-to-r from-blue-600 to-indigo-600 p-8 text-white shadow-lg">
        <h1 className="text-3xl font-bold tracking-tight">
          欢迎使用物理题库系统
        </h1>
        <p className="mt-2 text-lg text-blue-100">
          文件优先的物理题库：存题、检索、组卷、导出
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat) => {
          const Icon = stat.icon;
          return (
            <div
              key={stat.label}
              className="rounded-xl border border-gray-200 bg-white p-6 transition-shadow hover:shadow-md"
            >
              <div className="flex items-center gap-4">
                <div className={`rounded-lg p-3 ${stat.bgColor}`}>
                  <Icon className={`h-6 w-6 ${stat.iconColor}`} />
                </div>
                <div>
                  <p className="text-2xl font-bold text-gray-900">
                    <PulsingNumber loading={stat.loading} value={stat.value} />
                  </p>
                  <p className="text-sm font-medium text-gray-600">
                    {stat.label}
                  </p>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Quick Action Cards */}
      <div>
        <h2 className="mb-4 text-xl font-semibold text-gray-900">快捷操作</h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {quickActions.map((action) => {
            const Icon = action.icon;
            return (
              <Link
                key={action.label}
                href={action.href}
                className="group rounded-xl border border-gray-200 bg-white p-6 transition-shadow hover:shadow-md"
              >
                <div
                  className={`inline-flex rounded-lg p-3 ${action.color} mb-4`}
                >
                  <Icon className="h-5 w-5 text-white" />
                </div>
                <h3 className="mb-1 text-lg font-semibold text-gray-900">
                  {action.label}
                </h3>
                <p className="text-sm text-gray-500">{action.description}</p>
                <div className="mt-4 flex items-center gap-1 text-sm font-medium text-blue-600 opacity-0 transition-opacity group-hover:opacity-100">
                  开始 <ArrowRight className="h-4 w-4" />
                </div>
              </Link>
            );
          })}
        </div>
      </div>
    </div>
  );
}
