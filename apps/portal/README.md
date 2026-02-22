# Consent Ledger Portal

Frontend for Consent Ledger with two modes:

- Admin: dashboard, consent list, consent detail + revoke flow.
- End-User: consent center with purpose toggles and history timeline.

## Stack

- Next.js (App Router) + TypeScript
- Tailwind CSS + shadcn/ui
- lucide-react
- TanStack Table

## Setup

1. Install dependencies:

```bash
npm install
```

2. Configure API base URL:

```bash
cp .env.example .env.local
```

Default:

```env
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

3. Run the app:

```bash
npm run dev
```

App runs at `http://localhost:3000`.

## Routes

- `/` landing page with mode switch
- `/admin` dashboard
- `/admin/consents` searchable/filterable consent list
- `/admin/consents/[id]` consent details with revoke + audit timeline
- `/user` consent center
