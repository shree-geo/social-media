import { ChangePasswordForm } from "@/components/password-forms";
import { CenteredPage } from "@/components/ui";

export const metadata = { title: "Set your password · Admin" };

export default function AdminChangePasswordPage() {
  return (
    <CenteredPage>
      <ChangePasswordForm realm="platform" firstLogin />
    </CenteredPage>
  );
}
