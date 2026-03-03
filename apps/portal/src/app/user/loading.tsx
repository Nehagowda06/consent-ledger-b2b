import { AppShell } from "@/components/app-shell";
import { Skeleton } from "@/components/ui/skeleton";

export default function UserLoading() {
  return (
    <AppShell
      mode="user"
      title="Consent Center"
      subtitle="Review what is active, opt out where needed, and keep a transparent history."
    >
      <div className="space-y-6">
        <Skeleton className="h-16 rounded-2xl" />
        <div className="grid gap-4 md:grid-cols-2">
          <Skeleton className="h-44 rounded-2xl" />
          <Skeleton className="h-44 rounded-2xl" />
          <Skeleton className="h-44 rounded-2xl" />
          <Skeleton className="h-44 rounded-2xl" />
        </div>
        <Skeleton className="h-64 rounded-2xl" />
      </div>
    </AppShell>
  );
}
