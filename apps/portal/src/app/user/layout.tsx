import { AppShell } from "@/components/app-shell";

export default function UserLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AppShell
      mode="user"
      title="Consent Center"
      subtitle="View and manage the consents you have given."
    >
      {children}
    </AppShell>
  );
}