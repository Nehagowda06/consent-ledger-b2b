"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, RotateCcw, Save } from "lucide-react";
import { createConsent, revokeConsent } from "@/lib/api";
import { AuditEvent, Consent } from "@/lib/types";
import { AuditTimeline } from "@/components/audit-timeline";
import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

type PurposeConfig = {
  key: string;
  label: string;
  description: string;
  optional: boolean;
};

const PURPOSES: PurposeConfig[] = [
  {
    key: "core_service",
    label: "Core Service Operations",
    description: "Required for account security, delivery, and fraud prevention.",
    optional: false,
  },
  {
    key: "product_updates",
    label: "Product Updates",
    description: "Release notes, changes, and quality-of-service updates.",
    optional: true,
  },
  {
    key: "marketing_emails",
    label: "Marketing Emails",
    description: "Newsletters, campaigns, and feature announcements.",
    optional: true,
  },
  {
    key: "analytics_optimization",
    label: "Analytics Optimization",
    description: "Usage analytics to improve workflows and product performance.",
    optional: true,
  },
];

type UserConsentCenterProps = {
  subjectId: string;
  consents: Consent[];
  history: AuditEvent[];
};

export function UserConsentCenter({ subjectId, consents, history }: UserConsentCenterProps) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const activeConsents = useMemo(
    () =>
      PURPOSES.reduce<Record<string, Consent | null>>((acc, purpose) => {
        const match =
          consents.find(
            (consent) => consent.purpose === purpose.key && consent.status === "ACTIVE",
          ) ?? null;
        acc[purpose.key] = match;
        return acc;
      }, {}),
    [consents],
  );

  const [selection, setSelection] = useState<Record<string, boolean>>(() =>
    PURPOSES.reduce<Record<string, boolean>>((acc, purpose) => {
      acc[purpose.key] = !!activeConsents[purpose.key];
      return acc;
    }, {}),
  );

  async function savePreferences() {
    setPending(true);
    setError(null);
    setNotice(null);

    try {
      for (const purpose of PURPOSES) {
        const existingConsent = activeConsents[purpose.key];
        const currentlyActive = !!existingConsent;
        const shouldBeActive = purpose.optional ? selection[purpose.key] : true;

        if (shouldBeActive && !currentlyActive) {
          await createConsent({
            subject_id: subjectId,
            purpose: purpose.key,
          });
        }

        if (!shouldBeActive && currentlyActive && existingConsent) {
          await revokeConsent(existingConsent.id);
        }
      }

      setNotice("Preferences saved.");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save preferences");
    } finally {
      setPending(false);
    }
  }

  function revokeAllOptional() {
    setSelection((current) => {
      const next = { ...current };
      PURPOSES.forEach((purpose) => {
        if (purpose.optional) next[purpose.key] = false;
      });
      return next;
    });
    setNotice("Optional purposes switched off. Click Save to apply.");
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-slate-200 bg-white p-4">
        <Badge className="border border-indigo-200 bg-indigo-50 text-indigo-700 hover:bg-indigo-50">
          Subject: {subjectId}
        </Badge>
        <div className="ml-auto flex gap-2">
          <Button variant="outline" onClick={revokeAllOptional} disabled={pending}>
            <RotateCcw className="mr-2 h-4 w-4" />
            Revoke all optional
          </Button>
          <Button onClick={savePreferences} disabled={pending} className="bg-indigo-500 hover:bg-indigo-600">
            <Save className="mr-2 h-4 w-4" />
            {pending ? "Saving..." : "Save"}
          </Button>
        </div>
      </div>

      {error ? <p className="text-sm text-rose-600">{error}</p> : null}
      {notice ? <p className="text-sm text-emerald-700">{notice}</p> : null}

      <section className="grid gap-4 md:grid-cols-2">
        {PURPOSES.map((purpose) => (
          <Card key={purpose.key} className="border-slate-200">
            <CardHeader className="pb-2">
              <div className="mb-2 flex items-start justify-between gap-2">
                <CardTitle className="text-base">{purpose.label}</CardTitle>
                <Badge
                  className={cn(
                    "border",
                    purpose.optional
                      ? "border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-50"
                      : "border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-50",
                  )}
                >
                  {purpose.optional ? "Optional" : "Required"}
                </Badge>
              </div>
              <p className="text-sm text-slate-600">{purpose.description}</p>
            </CardHeader>
            <CardContent className="flex items-center justify-between pt-1">
              <p className="text-sm text-slate-700">
                {selection[purpose.key] ? "Enabled" : "Disabled"}
              </p>
              <Switch
                checked={purpose.optional ? selection[purpose.key] : true}
                onCheckedChange={(checked) => {
                  if (!purpose.optional) return;
                  setSelection((current) => ({ ...current, [purpose.key]: checked }));
                }}
                disabled={!purpose.optional || pending}
              />
            </CardContent>
          </Card>
        ))}
      </section>

      {!history.length ? (
        <EmptyState
          title="No consent history yet"
          description="Enable a purpose and save to create your first verified consent event."
          action={
            <div className="inline-flex items-center gap-2 text-sm text-emerald-700">
              <CheckCircle2 className="h-4 w-4" />
              Trust logs will appear here
            </div>
          }
        />
      ) : (
        <AuditTimeline events={history} title="Your Consent History" />
      )}
    </div>
  );
}
