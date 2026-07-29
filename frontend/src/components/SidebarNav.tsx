'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Book, BookOpen, FileText, Home, ListTree, Upload } from 'lucide-react';

const navItems = [
  { href: '/', label: '首页', icon: Home },
  { href: '/questions', label: '题库', icon: BookOpen },
  { href: '/knowledge-points', label: '知识点', icon: ListTree },
  { href: '/papers/generator', label: '组卷', icon: FileText },
  { href: '/upload', label: '导入资料', icon: Upload },
] as const;

export default function SidebarNav() {
  const pathname = usePathname();

  const isActive = (href: string) => {
    if (href === '/') return pathname === '/';
    return pathname.startsWith(href);
  };

  return (
    <>
      {/* Desktop Sidebar */}
      <aside className="fixed left-0 top-0 z-30 hidden h-screen w-64 flex-col border-r border-gray-200 bg-white md:flex">
        {/* Logo / Brand */}
        <div className="flex items-center gap-3 border-b border-gray-200 px-6 py-5">
          <Book className="h-7 w-7 text-blue-600" />
          <span className="text-lg font-bold text-gray-900">
            物理题库系统
          </span>
        </div>

        {/* Navigation */}
        <nav className="flex-1 space-y-1 px-3 py-6">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors ${
                  active
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                }`}
              >
                <Icon className="h-5 w-5 flex-shrink-0" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="border-t border-gray-200 px-6 py-4">
          <p className="text-xs text-gray-400">
            Physics Question Bank v0.1
          </p>
        </div>
      </aside>

      {/* Mobile Bottom Navigation */}
      <nav className="fixed bottom-0 left-0 right-0 z-30 border-t border-gray-200 bg-white md:hidden">
        <div className="flex items-center justify-around py-2">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex flex-col items-center gap-1 px-3 py-1.5 text-xs font-medium transition-colors ${
                  active
                    ? 'text-blue-600'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                <Icon className="h-5 w-5" />
                {item.label}
              </Link>
            );
          })}
        </div>
        {/* Safe area padding for notched phones */}
        <div className="h-safe-area-bottom" />
      </nav>

      {/* Bottom padding for mobile to offset the tab bar */}
      <div className="h-16 md:hidden" />
    </>
  );
}
