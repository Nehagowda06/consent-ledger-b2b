import { Badge } from "@/components/ui/badge";
import { ConsentStatus } from "@/lib/types";

export function StatusBadge({ status }: { status: ConsentStatus }) {
  if (status === "ACTIVE") {
    return (
      <Badge className="border border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-50">
        Active
      </Badge>
    );
  }

  return (
    <Badge className="border border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-50">
      Revoked
    </Badge>
  );
}
