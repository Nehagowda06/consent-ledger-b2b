export function shortId(id: string): string {
  return id.slice(0, 8);
}

export function formatDate(value?: string | null): string {
  if (!value) return "N/A";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
