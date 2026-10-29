import { AdminShell } from "@/components/admin-shell";

import { PlansList } from "./plans-list";

export const metadata = { title: "Packages · Admin" };

export default function PlansPage() {
  return (
    <AdminShell>
      <PlansList />
    </AdminShell>
  );
}
