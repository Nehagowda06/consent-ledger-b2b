import Link from "next/link";
import { Search } from "lucide-react";
import { listConsents } from "@/lib/api";
import { AdminConsentsTable } from "@/components/admin-consents-table";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type SearchParams = Promise<{
  subject_id?: string;
  status?: "ACTIVE" | "REVOKED";
}>;

export default async function AdminConsentsPage(props: { searchParams: SearchParams }) {
  const searchParams = await props.searchParams;
  const subjectId = searchParams.subject_id?.trim() || "";
  const status = searchParams.status;

  const consents = await listConsents(subjectId || undefined);
  const filteredConsents = status
    ? consents.filter((consent) => consent.status === status)
    : consents;

  return (
    <div className="space-y-5">
      <form className="rounded-2xl border border-slate-200 bg-white p-4">
        <div className="grid gap-3 md:grid-cols-[1fr,200px,auto]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 text-slate-400" />
            <Input
              name="subject_id"
              placeholder="Search by subject_id"
              defaultValue={subjectId}
              className="pl-9"
            />
          </div>
          <select
            name="status"
            defaultValue={status || ""}
            className="h-10 rounded-md border border-slate-200 bg-white px-3 text-sm"
          >
            <option value="">All status</option>
            <option value="ACTIVE">Active</option>
            <option value="REVOKED">Revoked</option>
          </select>
          <Button type="submit" className="bg-indigo-500 hover:bg-indigo-600">
            Apply
          </Button>
        </div>
      </form>

      {!filteredConsents.length ? (
        <EmptyState
          title="No matching consents"
          description="Try a different subject or status filter to locate records."
          action={
            <Button asChild variant="outline">
              <Link href="/admin/consents">Clear filters</Link>
            </Button>
          }
        />
      ) : (
        <AdminConsentsTable data={filteredConsents} />
      )}
    </div>
  );
}
