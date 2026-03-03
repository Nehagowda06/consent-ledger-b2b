import { listConsents, getConsentAudit } from "@/lib/api";
import { AuditTimeline } from "@/components/audit-timeline";
import { EmptyState } from "@/components/empty-state";

type SearchParams = Promise<{
  subject_id?: string;
}>;

export default async function UserPage(props: {
  searchParams: SearchParams;
}) {
  const searchParams = await props.searchParams;
  const subjectId = searchParams.subject_id?.trim();

  // IMPORTANT FIX: unwrap { data }
  const response = await listConsents(subjectId || undefined);
  const consents = response.data;

  if (!consents.length) {
    return (
      <EmptyState
        title="No consents found"
        description="There are no consents available for this subject."
      />
    );
  }

  // Fetch audit history safely
  const history = (
    await Promise.all(
      consents.map(async (consent) => {
        try {
          return await getConsentAudit(consent.id);
        } catch {
          return [];
        }
      })
    )
  )
    .flat()
    .sort(
      (a, b) =>
        new Date(b.at).getTime() - new Date(a.at).getTime()
    );

  return (
    <div className="space-y-6">
      {history.length ? (
        <AuditTimeline
          events={history}
          title="Consent Activity"
        />
      ) : (
        <EmptyState
          title="No activity yet"
          description="No audit events have been recorded for these consents."
        />
      )}
    </div>
  );
}
