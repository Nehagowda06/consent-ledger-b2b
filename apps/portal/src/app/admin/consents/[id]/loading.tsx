import { Skeleton } from "@/components/ui/skeleton";

export default function AdminConsentDetailsLoading() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-10 w-40" />
      <Skeleton className="h-52 rounded-2xl" />
      <Skeleton className="h-72 rounded-2xl" />
    </div>
  );
}
