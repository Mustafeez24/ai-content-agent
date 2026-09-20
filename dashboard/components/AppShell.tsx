import Link from "next/link";

export default function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-4">
          <span className="text-lg font-semibold">FlyingFish Content</span>
          <nav className="flex gap-4 text-sm text-slate-600">
            <Link href="/" className="hover:text-slate-900">
              Dashboard
            </Link>
            <Link href="/calendar" className="hover:text-slate-900">
              Calendar
            </Link>
            <Link href="/content" className="hover:text-slate-900">
              Content
            </Link>
            <Link href="/exports" className="hover:text-slate-900">
              Exports
            </Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
