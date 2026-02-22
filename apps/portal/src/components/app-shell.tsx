import Link from "next/link";
import { cn } from "@/lib/utils";
import { TopNavbar } from "@/components/top-navbar";
import { SiteFooter } from "@/components/site-footer";

type AppShellProps = {
  children: React.ReactNode;
  mode: "admin" | "user";
  title: string;
  subtitle: string;
  actions?: React.ReactNode;
};

export function AppShell({ children, mode, title, subtitle, actions }: AppShellProps) {
  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      <header className="hero-shell border-b border-indigo-500/20 text-slate-100">
        <TopNavbar dark />
        <div className="mx-auto flex w-full max-w-6xl items-center justify-end px-6 py-4">
          <nav className="flex items-center gap-2 rounded-full bg-white/10 p-1 text-sm">
            <Link
              href="/admin"
              className={cn(
                "rounded-full px-3 py-1.5 transition",
                mode === "admin" ? "bg-white text-slate-950" : "text-white/80 hover:text-white",
              )}
            >
              Admin
            </Link>
            <Link
              href="/user"
              className={cn(
                "rounded-full px-3 py-1.5 transition",
                mode === "user" ? "bg-white text-slate-950" : "text-white/80 hover:text-white",
              )}
            >
              End-User
            </Link>
          </nav>
        </div>
        <div className="mx-auto flex w-full max-w-6xl items-end justify-between gap-4 px-6 pb-8 pt-2">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-300">
              Trust and Compliance
            </p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">{title}</h1>
            <p className="mt-1 text-slate-300">{subtitle}</p>
          </div>
          {actions}
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">{children}</main>
      <SiteFooter />
    </div>
  );
}
