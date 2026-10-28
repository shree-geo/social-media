import { TenantShell } from "@/components/tenant-shell";

export default function TenantLayout({ children }: LayoutProps<"/">) {
  return <TenantShell>{children}</TenantShell>;
}
