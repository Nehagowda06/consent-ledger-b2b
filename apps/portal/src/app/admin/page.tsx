import { Activity, ShieldAlert, ShieldCheck } from "lucide-react";
import { listConsents, getConsentAudit } from "@/lib/api";
import { KpiCard } from "@/components/kpi-card";
import { QuickCreateConsent } from "@/components/quick-create-consent";
import { AuditTimeline } from "@/components/audit-timeline";
import { EmptyState } from "@/components/empty-state";

export default async function AdminDashboardPage() {
  const consents = await listConsents();
  const activeCount = consents.filter((consent) => consent.status === "ACTIVE").length;

  const now = new Date();
  const today = now.toISOString().slice(0, 10);
  const revokedToday = consents.filter(
    (consent) => consent.revoked_at && consent.revoked_at.slice(0, 10) === today,
  ).length;

  const recent = [...consents]
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    .slice(0, 6);

  const audits = await Promise.all(recent.map((consent) => getConsentAudit(consent.id)));
  const timelineEvents = audits
    .flat()
    .sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime())
    .slice(0, 10);

  return (
    <div className="space-y-6">
      <section className="flex justify-end">
        <QuickCreateConsent />
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        <KpiCard
          label="Active"
          value={activeCount}
          hint="Currently valid consents"
          icon={<ShieldCheck className="h-5 w-5" />}
        />
        <KpiCard
          label="Revoked Today"
          value={revokedToday}
          hint="Revocations in the last 24 hours"
          icon={<ShieldAlert className="h-5 w-5" />}
        />
        <KpiCard
          label="Total Events"
          value={timelineEvents.length}
          hint="Recent trust events collected"
          icon={<Activity className="h-5 w-5" />}
        />
      </section>

      {timelineEvents.length ? (
        <AuditTimeline events={timelineEvents} title="Recent Activity" />
      ) : (
        <EmptyState
          title="No recent activity"
          description="Create a consent to start generating an audit trail for your compliance timeline."
          action={<QuickCreateConsent />}
        />
      )}
    </div>
  );
}
