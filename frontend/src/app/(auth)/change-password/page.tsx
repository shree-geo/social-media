import { ChangePasswordForm } from "@/components/password-forms";
import { CenteredPage } from "@/components/ui";

export const metadata = { title: "Set your password · SocialCommerce" };

export default function ChangePasswordPage() {
  return (
    <CenteredPage>
      <ChangePasswordForm realm="tenant" firstLogin />
    </CenteredPage>
  );
}
