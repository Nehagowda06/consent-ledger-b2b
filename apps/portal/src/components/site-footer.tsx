import Link from "next/link";
import { Github, Linkedin, Twitter } from "lucide-react";

export function SiteFooter() {
  return (
    <footer className="border-t border-slate-200 bg-white">
      <div className="mx-auto grid w-full max-w-6xl gap-8 px-6 py-10 md:grid-cols-3">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">
            Consent Ledger
          </h3>
          <p className="mt-3 max-w-xs text-sm text-slate-600">
            Trusted consent infrastructure for transparent compliance workflows.
          </p>
        </div>
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">
            Company
          </h3>
          <div className="mt-3 flex flex-col gap-2 text-sm text-slate-600">
            <Link href="/about" className="hover:text-slate-900">
              About
            </Link>
            <Link href="/contact" className="hover:text-slate-900">
              Contact
            </Link>
            <Link href="/admin" className="hover:text-slate-900">
              Admin
            </Link>
            <Link href="/user" className="hover:text-slate-900">
              Consent Center
            </Link>
          </div>
        </div>
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">
            Social
          </h3>
          <div className="mt-3 flex items-center gap-3">
            <Link href="#" className="rounded-full border border-slate-200 p-2 text-slate-600 hover:text-slate-900">
              <Twitter className="h-4 w-4" />
            </Link>
            <Link href="#" className="rounded-full border border-slate-200 p-2 text-slate-600 hover:text-slate-900">
              <Linkedin className="h-4 w-4" />
            </Link>
            <Link href="#" className="rounded-full border border-slate-200 p-2 text-slate-600 hover:text-slate-900">
              <Github className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
