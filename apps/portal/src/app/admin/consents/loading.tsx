import { Skeleton } from "@/components/ui/skeleton";

export default function AdminConsentsLoading() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-20 rounded-2xl" />
      <Skeleton className="h-96 rounded-2xl" />
    </div>
  );
}
