import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { getConsent, getConsentAudit } from "@/lib/api";
import { formatDate, shortId } from "@/lib/format";
import { AuditTimeline } from "@/components/audit-timeline";
import { EmptyState } from "@/components/empty-state";
import { RevokeConsentButton } from "@/components/revoke-consent-button";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type RouteParams = Promise<{ id: string }>;

export default async function AdminConsentDetailsPage(props: { params: RouteParams }) {
  const { id } = await props.params;
  let consentData: Awaited<ReturnType<typeof getConsent>> | null = null;
  let eventsData: Awaited<ReturnType<typeof getConsentAudit>> = [];
  let loadFailed = false;

  try {
    const [consent, events] = await Promise.all([getConsent(id), getConsentAudit(id)]);
    consentData = consent;
    eventsData = events;
  } catch {
    loadFailed = true;
  }

  if (loadFailed || !consentData) {
    return (
      <EmptyState
        title="Consent not found"
        description="The consent may not exist or is no longer accessible."
        action={
          <Button asChild variant="outline">
            <Link href="/admin/consents">Return to consents</Link>
          </Button>
        }
      />
    );
  }

  return (
    <div className="space-y-6">
      <Button asChild variant="outline">
        <Link href="/admin/consents">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to list
        </Link>
      </Button>

      <Card className="border-slate-200">
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <CardTitle className="text-2xl tracking-tight">
                Consent {shortId(consentData.id)}
              </CardTitle>
              <p className="mt-2 text-sm text-slate-600">Subject: {consentData.subject_id}</p>
              <p className="mt-1 text-sm text-slate-600">Purpose: {consentData.purpose}</p>
            </div>
            <div className="flex items-center gap-3">
              <StatusBadge status={consentData.status} />
              <RevokeConsentButton
                consentId={consentData.id}
                disabled={consentData.status === "REVOKED"}
              />
            </div>
          </div>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm text-slate-600">
          <p>Created: {formatDate(consentData.created_at)}</p>
          <p>Updated: {formatDate(consentData.updated_at)}</p>
          <p>Revoked: {formatDate(consentData.revoked_at)}</p>
        </CardContent>
      </Card>

      <AuditTimeline events={eventsData} title="Consent Audit Trail" />
    </div>
  );
}
