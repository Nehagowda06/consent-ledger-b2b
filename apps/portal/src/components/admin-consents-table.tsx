"use client";

import Link from "next/link";
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { Eye } from "lucide-react";
import { Consent } from "@/lib/types";
import { shortId, formatDate } from "@/lib/format";
import { StatusBadge } from "@/components/status-badge";
import { RevokeConsentButton } from "@/components/revoke-consent-button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";

export function AdminConsentsTable({ data }: { data: Consent[] }) {
  const columns: ColumnDef<Consent>[] = [
    {
      header: "Consent ID",
      accessorKey: "id",
      cell: ({ row }) => <span className="font-mono text-sm">{shortId(row.original.id)}</span>,
    },
    {
      header: "Subject",
      accessorKey: "subject_id",
    },
    {
      header: "Purpose",
      accessorKey: "purpose",
    },
    {
      header: "Status",
      accessorKey: "status",
      cell: ({ row }) => <StatusBadge status={row.original.status} />,
    },
    {
      header: "Updated",
      accessorKey: "updated_at",
      cell: ({ row }) => formatDate(row.original.updated_at),
    },
    {
      id: "actions",
      header: "Actions",
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <Button asChild size="sm" variant="outline">
            <Link href={`/admin/consents/${row.original.id}`}>
              <Eye className="mr-1.5 h-3.5 w-3.5" />
              View
            </Link>
          </Button>
          <RevokeConsentButton consentId={row.original.id} disabled={row.original.status === "REVOKED"} size="sm" />
        </div>
      ),
    },
  ];

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHead key={header.id}>
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.map((row) => (
            <TableRow key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <TableCell key={cell.id}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
