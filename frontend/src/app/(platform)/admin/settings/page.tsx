import { AdminShell } from "@/components/admin-shell";

import { SettingsForm } from "./settings-form";

export const metadata = { title: "Settings · Admin" };

export default function SettingsPage() {
  return (
    <AdminShell>
      <SettingsForm />
    </AdminShell>
  );
}
