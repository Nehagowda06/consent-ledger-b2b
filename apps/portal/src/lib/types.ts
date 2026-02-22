export type ConsentStatus = "ACTIVE" | "REVOKED";

export type Consent = {
  id: string;
  subject_id: string;
  purpose: string;
  status: ConsentStatus;
  created_at: string;
  updated_at: string;
  revoked_at?: string | null;
};

export type AuditEvent = {
  consent_id: string;
  action: string;
  actor: string;
  at: string;
};

export type ConsentCreateInput = {
  subject_id: string;
  purpose: string;
};
