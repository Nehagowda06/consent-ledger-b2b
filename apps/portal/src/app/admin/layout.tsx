import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppShell
      mode="admin"
      title="Admin Console"
      subtitle="Monitor, verify, and manage all consent operations."
      actions={
        <div className="flex gap-2">
          <Button asChild variant="secondary" className="bg-white/15 text-white hover:bg-white/25">
            <Link href="/admin">Dashboard</Link>
          </Button>
          <Button asChild variant="secondary" className="bg-white/15 text-white hover:bg-white/25">
            <Link href="/admin/consents">Consents</Link>
          </Button>
        </div>
      }
    >
      {children}
    </AppShell>
  );
}
