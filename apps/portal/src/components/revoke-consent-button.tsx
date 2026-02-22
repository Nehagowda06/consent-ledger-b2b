"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle } from "lucide-react";
import { revokeConsent } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

type RevokeConsentButtonProps = {
  consentId: string;
  disabled?: boolean;
  size?: "default" | "sm" | "lg" | "icon";
};

export function RevokeConsentButton({
  consentId,
  disabled,
  size = "default",
}: RevokeConsentButtonProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onConfirm() {
    setPending(true);
    setError(null);

    try {
      await revokeConsent(consentId);
      setOpen(false);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not revoke consent");
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="destructive"
          size={size}
          disabled={disabled || pending}
          className="bg-rose-500 hover:bg-rose-600"
        >
          Revoke
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-rose-500" />
            Revoke this consent?
          </DialogTitle>
          <DialogDescription>
            This will mark the consent as revoked and record an audit event.
          </DialogDescription>
        </DialogHeader>
        {error ? <p className="text-sm text-rose-600">{error}</p> : null}
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={pending}>
            Cancel
          </Button>
          <Button onClick={onConfirm} disabled={pending} className="bg-rose-500 hover:bg-rose-600">
            {pending ? "Revoking..." : "Confirm Revoke"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
