import { AuditEvent, Consent, ConsentCreateInput } from "@/lib/types";

/* =======================
   ENV
======================= */
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.trim() ||
  "http://127.0.0.1:8000";

const ADMIN_API_KEY =
  process.env.NEXT_PUBLIC_ADMIN_API_KEY?.trim();

const TENANT_API_KEY =
  process.env.NEXT_PUBLIC_TENANT_API_KEY?.trim();

/* =======================
   TYPES
======================= */
export type Paginated<T> = {
  data: T[];
  meta: {
    limit: number;
    offset: number;
    count: number;
  };
};

/* =======================
   HEADERS
======================= */
function buildHeaders(path: string): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (path.startsWith("/admin")) {
    if (!ADMIN_API_KEY) {
      throw new Error("NEXT_PUBLIC_ADMIN_API_KEY is missing");
    }
    headers["X-Admin-Api-Key"] = ADMIN_API_KEY;
    return headers;
  }

  if (!TENANT_API_KEY) {
    throw new Error("NEXT_PUBLIC_TENANT_API_KEY is missing");
  }

  headers["X-Api-Key"] = TENANT_API_KEY;
  return headers;
}

/* =======================
   REQUEST CORE
======================= */
async function request<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      ...buildHeaders(path),
      ...(init.headers || {}),
    },
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`API ${response.status}: ${text}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

/* =======================
   CONSENTS
======================= */
export async function listConsents(
  subjectId?: string
): Promise<Paginated<Consent>> {
  const query = subjectId
    ? `?subject_id=${encodeURIComponent(subjectId)}`
    : "";

  return request<Paginated<Consent>>(`/consents${query}`);
}

export async function getConsent(id: string): Promise<Consent> {
  return request<Consent>(`/consents/${id}`);
}

export async function createConsent(
  payload: ConsentCreateInput
): Promise<Consent> {
  return request<Consent>("/consents", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function revokeConsent(id: string): Promise<Consent> {
  return request<Consent>(`/consents/${id}/revoke`, {
    method: "POST",
  });
}

export async function getConsentAudit(
  id: string
): Promise<AuditEvent[]> {
  return request<AuditEvent[]>(`/consents/${id}/audit`);
}
