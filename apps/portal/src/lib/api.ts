import { AuditEvent, Consent, ConsentCreateInput } from "@/lib/types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.trim() ||
  "http://127.0.0.1:8000";

// Admin API key for demo / MVP
const ADMIN_API_KEY =
  process.env.NEXT_PUBLIC_ADMIN_API_KEY?.trim() || "";

/**
 * Central request helper
 */
async function request<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    cache: "no-store", // REQUIRED for Next.js App Router
    headers: {
      "Content-Type": "application/json",

      // 🔐 Admin authentication header
      ...(ADMIN_API_KEY
        ? { "X-Admin-Api-Key": ADMIN_API_KEY }
        : {}),

      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`API ${response.status}: ${text}`);
  }

  // Handle empty responses
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
): Promise<Consent[]> {
  const query = subjectId
    ? `?subject_id=${encodeURIComponent(subjectId)}`
    : "";
  return request<Consent[]>(`/consents${query}`);
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
export async function getConsentAudit(
  id: string
): Promise<AuditEvent[]> {
  return request<AuditEvent[]>(`/consents/${id}/audit`);
}
