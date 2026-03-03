import { Card, CardContent } from "@/components/ui/card";

type KpiCardProps = {
  label: string;
  value: string | number;
  hint: string;
  icon: React.ReactNode;
};

export function KpiCard({ label, value, hint, icon }: KpiCardProps) {
  return (
    <Card className="border-slate-200 shadow-sm">
      <CardContent className="flex items-start justify-between p-5">
        <div>
          <p className="text-sm text-slate-500">{label}</p>
          <p className="mt-2 text-3xl font-semibold tracking-tight text-slate-900">{value}</p>
          <p className="mt-1 text-xs text-slate-500">{hint}</p>
        </div>
        <div className="rounded-xl bg-indigo-50 p-2 text-indigo-600">{icon}</div>
      </CardContent>
    </Card>
  );
}
