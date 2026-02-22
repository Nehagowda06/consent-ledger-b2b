import { CheckCircle2, ShieldCheck, Users } from "lucide-react";
import { TopNavbar } from "@/components/top-navbar";
import { SiteFooter } from "@/components/site-footer";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

const FAQ_ITEMS = [
  {
    question: "How does Consent Ledger help with compliance?",
    answer:
      "Every consent creation and revocation is recorded in an auditable timeline so teams can verify user intent and demonstrate governance.",
  },
  {
    question: "Can both admins and end-users manage consent?",
    answer:
      "Yes. Admins can monitor and revoke at the organization level while end-users can update optional preferences from the Consent Center.",
  },
  {
    question: "Is the consent history tamper-evident?",
    answer:
      "The UI is designed around immutable audit events from the backend, making trust and traceability the centerpiece of daily operations.",
  },
];

export default function AboutPage() {
  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      <section className="hero-shell">
        <TopNavbar dark />
        <div className="mx-auto w-full max-w-5xl px-6 py-18 text-white">
          <p className="text-xs uppercase tracking-[0.2em] text-slate-300">About Consent Ledger</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight">Built for trust-first data operations.</h1>
          <p className="mt-3 max-w-3xl text-slate-300">
            Consent Ledger gives B2B teams a clear, usable system to capture consent and prove compliance with confidence.
          </p>
        </div>
      </section>

      <main className="mx-auto w-full max-w-5xl flex-1 space-y-6 px-6 py-10">
        <section className="grid gap-4 md:grid-cols-3">
          <Card className="border-slate-200">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <ShieldCheck className="h-5 w-5 text-indigo-600" />
                Verifiable Events
              </CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-slate-600">
              Every action is timestamped and preserved in timeline form.
            </CardContent>
          </Card>
          <Card className="border-slate-200">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <Users className="h-5 w-5 text-emerald-600" />
                Dual-Mode UX
              </CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-slate-600">
              Separate Admin and Consent Center experiences with shared trust signals.
            </CardContent>
          </Card>
          <Card className="border-slate-200">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <CheckCircle2 className="h-5 w-5 text-indigo-600" />
                Clear Controls
              </CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-slate-600">
              Active/Revoked status, empty states, and guided actions reduce errors.
            </CardContent>
          </Card>
        </section>

        <Card className="border-slate-200">
          <CardHeader>
            <CardTitle>FAQ</CardTitle>
            <CardDescription>Common questions about trust, workflows, and compliance operations.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {FAQ_ITEMS.map((item, idx) => (
              <div key={item.question}>
                <h3 className="text-sm font-semibold text-slate-900">{item.question}</h3>
                <p className="mt-1 text-sm text-slate-600">{item.answer}</p>
                {idx < FAQ_ITEMS.length - 1 ? <Separator className="mt-4" /> : null}
              </div>
            ))}
          </CardContent>
        </Card>
      </main>
      <SiteFooter />
    </div>
  );
}
