"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { createConsent } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

export function QuickCreateConsent() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [subjectId, setSubjectId] = useState("");
  const [purpose, setPurpose] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onCreate() {
    setPending(true);
    setError(null);

    try {
      await createConsent({
        subject_id: subjectId.trim(),
        purpose: purpose.trim(),
      });
      setOpen(false);
      setSubjectId("");
      setPurpose("");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create consent");
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="bg-indigo-500 text-white hover:bg-indigo-600">
          <Plus className="mr-2 h-4 w-4" />
          Quick create consent
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create Consent</DialogTitle>
          <DialogDescription>Add a new consent entry for a subject and purpose.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <Input
            placeholder="subject_id (e.g. user_123)"
            value={subjectId}
            onChange={(event) => setSubjectId(event.target.value)}
          />
          <Input
            placeholder="purpose (e.g. marketing_emails)"
            value={purpose}
            onChange={(event) => setPurpose(event.target.value)}
          />
          {error ? <p className="text-sm text-rose-600">{error}</p> : null}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={pending}>
            Cancel
          </Button>
          <Button
            onClick={onCreate}
            disabled={pending || !subjectId.trim() || !purpose.trim()}
            className="bg-indigo-500 hover:bg-indigo-600"
          >
            {pending ? "Creating..." : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
