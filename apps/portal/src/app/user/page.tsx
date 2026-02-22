import { AppShell } from "@/components/app-shell";
import { UserConsentCenter } from "@/components/user-consent-center";
import { getConsentAudit, listConsents } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type SearchParams = Promise<{ subject_id?: string }>;

export default async function UserPage(props: { searchParams: SearchParams }) {
  const searchParams = await props.searchParams;
  const subjectId = searchParams.subject_id?.trim() || "demo_user_001";

  const consents = await listConsents(subjectId);
  const history = (
    await Promise.all(consents.map((consent) => getConsentAudit(consent.id)))
  )
    .flat()
    .sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime());

  return (
    <AppShell
      mode="user"
      title="Consent Center"
      subtitle="Review what is active, opt out where needed, and keep a transparent history."
    >
      <div className="space-y-6">
        <form className="flex flex-wrap gap-2 rounded-2xl border border-slate-200 bg-white p-4">
          <Input
            name="subject_id"
            defaultValue={subjectId}
            className="max-w-sm"
            placeholder="Subject ID"
          />
          <Button type="submit" className="bg-indigo-500 hover:bg-indigo-600">
            Load Subject
          </Button>
        </form>
        <UserConsentCenter subjectId={subjectId} consents={consents} history={history} />
      </div>
    </AppShell>
  );
}
