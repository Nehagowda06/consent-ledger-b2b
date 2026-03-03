import Link from "next/link";
import { ArrowRight, Building2, UserRound } from "lucide-react";
import { TopNavbar } from "@/components/top-navbar";
import { SiteFooter } from "@/components/site-footer";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function HomePage() {
  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      <section className="hero-shell">
        <TopNavbar dark />
        <div className="mx-auto max-w-5xl px-6 py-24 text-white">
          <p className="text-xs uppercase tracking-[0.24em] text-slate-300">Consent Ledger</p>
          <h1 className="mt-4 max-w-2xl text-5xl font-semibold leading-tight tracking-tight">
            Trust-first consent infrastructure for modern B2B products.
          </h1>
          <p className="mt-4 max-w-2xl text-slate-300">
            Manage subject consent with auditable trails and clear controls across Admin and End-User experiences.
          </p>
        </div>
      </section>

      <main className="mx-auto grid w-full max-w-5xl flex-1 gap-4 px-6 py-10 md:grid-cols-2">
        <Card className="border-slate-200">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Building2 className="h-5 w-5 text-indigo-600" />
              Admin Mode
            </CardTitle>
            <CardDescription>
              Monitor consent status, review events, and revoke with full audit visibility.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild className="bg-indigo-500 hover:bg-indigo-600">
              <Link href="/admin">
                Open Dashboard
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </CardContent>
        </Card>

        <Card className="border-slate-200">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <UserRound className="h-5 w-5 text-emerald-600" />
              End-User Mode
            </CardTitle>
            <CardDescription>
              Provide transparent controls where users can review, update, or revoke optional purposes.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild variant="outline">
              <Link href="/user">
                Open Consent Center
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </CardContent>
        </Card>
      </main>
      <SiteFooter />
    </div>
  );
}
