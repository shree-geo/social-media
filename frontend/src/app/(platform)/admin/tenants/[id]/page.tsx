import { Suspense } from "react";

import { AdminShell } from "@/components/admin-shell";
import { Spinner } from "@/components/ui";

import { TenantDetailView } from "./tenant-detail";

export const metadata = { title: "Business · Admin" };

export default function TenantPage() {
  return (
    <AdminShell>
      <Suspense fallback={<Spinner />}>
        <TenantDetailView />
      </Suspense>
    </AdminShell>
  );
}
