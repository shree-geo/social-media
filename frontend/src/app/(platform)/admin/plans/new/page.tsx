import { AdminShell } from "@/components/admin-shell";

import { NewPlanForm } from "./new-plan-form";

export const metadata = { title: "New package · Admin" };

export default function NewPlanPage() {
  return (
    <AdminShell>
      <NewPlanForm />
    </AdminShell>
  );
}
