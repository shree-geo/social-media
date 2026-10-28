import { AdminShell } from "@/components/admin-shell";

import { TenantsList } from "./tenants-list";

export const metadata = { title: "Tenants · Admin" };

export default function TenantsPage() {
  return (
    <AdminShell>
      <TenantsList />
    </AdminShell>
  );
}
