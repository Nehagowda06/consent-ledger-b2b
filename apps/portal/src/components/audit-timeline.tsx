import { ShieldCheck, ShieldX } from "lucide-react";
import { AuditEvent } from "@/lib/types";
import { formatDate, shortId } from "@/lib/format";
import { EmptyState } from "@/components/empty-state";
import { cn } from "@/lib/utils";

type AuditTimelineProps = {
  events: AuditEvent[];
  title?: string;
  className?: string;
};

export function AuditTimeline({
  events,
  title = "Audit Timeline",
  className,
}: AuditTimelineProps) {
  if (!events.length) {
    return (
      <div className={cn("rounded-2xl border border-slate-200 bg-white p-4", className)}>
        <EmptyState
          title="No audit events yet"
          description="New consent actions will appear here and become your compliance history."
        />
      </div>
    );
  }

  return (
    <section className={cn("rounded-2xl border border-slate-200 bg-white p-5", className)}>
      <div className="mb-5 flex items-center justify-between">
        <h2 className="text-lg font-semibold tracking-tight text-slate-900">{title}</h2>
        <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Traceability</p>
      </div>
      <ol className="relative space-y-5 border-l border-slate-200 pl-5">
        {events.map((event) => {
          const revoked = event.action === "REVOKED";
          return (
            <li key={`${event.consent_id}-${event.at}-${event.action}`} className="relative">
              <span
                className={cn(
                  "absolute -left-[1.70rem] top-0 inline-flex h-6 w-6 items-center justify-center rounded-full border bg-white",
                  revoked ? "border-rose-200 text-rose-600" : "border-emerald-200 text-emerald-600",
                )}
              >
                {revoked ? <ShieldX className="h-3.5 w-3.5" /> : <ShieldCheck className="h-3.5 w-3.5" />}
              </span>
              <p className="text-sm font-medium text-slate-900">
                {revoked ? "Consent Revoked" : "Consent Created"}
              </p>
              <p className="mt-1 text-xs text-slate-600">
                Consent <span className="font-mono">{shortId(event.consent_id)}</span> by {event.actor}
              </p>
              <p className="mt-1 text-xs text-slate-500">{formatDate(event.at)}</p>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
