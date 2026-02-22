import { FileClock } from "lucide-react";

type EmptyStateProps = {
  title: string;
  description: string;
  action?: React.ReactNode;
};

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-8 py-12 text-center">
      <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-slate-100">
        <FileClock className="h-5 w-5 text-slate-500" />
      </div>
      <h3 className="text-lg font-semibold tracking-tight text-slate-900">{title}</h3>
      <p className="mx-auto mt-2 max-w-md text-sm text-slate-600">{description}</p>
      {action ? <div className="mt-6">{action}</div> : null}
    </div>
  );
}
