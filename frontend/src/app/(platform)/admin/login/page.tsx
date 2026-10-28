import { LoginForm } from "@/components/password-forms";
import { CenteredPage } from "@/components/ui";

export const metadata = { title: "Admin login · SocialCommerce" };

export default function AdminLoginPage() {
  return (
    <CenteredPage>
      <LoginForm realm="platform" title="Platform admin" />
    </CenteredPage>
  );
}
