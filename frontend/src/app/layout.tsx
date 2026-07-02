import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import SidebarNav from '@/components/SidebarNav';
import './globals.css';
import 'katex/dist/katex.min.css';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: '物理题库系统',
  description: '面向物理教学的智能题库平台',
  icons: {
    icon: '/icon.svg',
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className={inter.className}>
        <div className="flex min-h-screen">
          <SidebarNav />

          {/* Main Content */}
          <main className="flex-1 md:ml-64">
            <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
              {children}
            </div>
          </main>
        </div>
      </body>
    </html>
  );
}
