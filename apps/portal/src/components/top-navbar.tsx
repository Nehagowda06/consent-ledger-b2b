"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/about", label: "About" },
  { href: "/contact", label: "Contact" },
  { href: "/admin", label: "Admin" },
  { href: "/user", label: "Consent Center" },
];

type TopNavbarProps = {
  dark?: boolean;
};

export function TopNavbar({ dark = false }: TopNavbarProps) {
  const pathname = usePathname();

  return (
    <div
      className={cn(
        "border-b",
        dark ? "border-indigo-500/20 bg-white/5" : "border-slate-200 bg-white",
      )}
    >
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-3">
        <Link
          href="/"
          className={cn(
            "flex items-center gap-2 font-semibold tracking-tight",
            dark ? "text-white" : "text-slate-900",
          )}
        >
          <ShieldCheck className="h-5 w-5 text-emerald-400" />
          <span>Consent Ledger</span>
        </Link>
        <nav className="flex flex-wrap items-center gap-1.5 text-sm">
          {LINKS.map((link) => {
            const active =
              link.href === "/"
                ? pathname === "/"
                : pathname === link.href || pathname.startsWith(`${link.href}/`);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "rounded-full px-3 py-1.5 transition",
                  dark
                    ? active
                      ? "bg-white text-slate-950"
                      : "text-white/80 hover:text-white"
                    : active
                      ? "bg-indigo-50 text-indigo-700"
                      : "text-slate-600 hover:text-slate-900",
                )}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </div>
  );
}
