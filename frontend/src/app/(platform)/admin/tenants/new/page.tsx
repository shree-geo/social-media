import { AdminShell } from "@/components/admin-shell";

import { NewTenantForm } from "./new-tenant-form";

export const metadata = { title: "Add a business · Admin" };

export default function NewTenantPage() {
  return (
    <AdminShell>
      <NewTenantForm />
    </AdminShell>
  );
}
