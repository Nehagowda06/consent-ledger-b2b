
import { Badge } from "@/components/ui/badge";
import { ConsentStatus } from "@/lib/types";

export function StatusBadge({ status }: { status: ConsentStatus }) {
  if (status === "ACTIVE") {
    return (
      <Badge
        variant="outline"
        className="border-emerald-300 bg-emerald-50 text-emerald-800"
      >
        Active
      </Badge>
    );
  }

  return (
    <Badge
      variant="outline"
      className="border-rose-300 bg-rose-50 text-rose-800"
    >
      Revoked
    </Badge>
  );
}
