import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import {
  LayoutDashboard,
  Upload,
  MessageSquare,
  TrendingUp,
} from "lucide-react";

export const metadata: Metadata = {
  title: "FinTech Intel — Financial Intelligence Platform",
  description: "AI-powered financial analytics for business insights",
};

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/upload", label: "Upload", icon: Upload },
  { href: "/chat", label: "Chat IA", icon: MessageSquare },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body className="flex h-screen overflow-hidden">
        {/* Sidebar */}
        <aside className="w-[220px] flex-shrink-0 bg-gray-900 text-white flex flex-col">
          {/* Logo */}
          <div className="flex items-center gap-2 px-5 py-5 border-b border-gray-700">
            <TrendingUp className="w-6 h-6 text-blue-400" />
            <span className="font-bold text-lg leading-tight">FinTech<br /><span className="text-blue-400 text-sm font-semibold">Intel</span></span>
          </div>

          {/* Nav */}
          <nav className="flex-1 py-4 px-3 space-y-1">
            {NAV_ITEMS.map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-gray-300 hover:text-white hover:bg-gray-700 transition-colors"
              >
                <Icon className="w-4 h-4 flex-shrink-0" />
                {label}
              </Link>
            ))}
          </nav>

          {/* Footer */}
          <div className="px-5 py-4 border-t border-gray-700 text-xs text-gray-500">
            AI Financial Intelligence v1.0
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-y-auto bg-gray-50">
          {children}
        </main>
      </body>
    </html>
  );
}
