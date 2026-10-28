import { LoginForm } from "@/components/password-forms";
import { CenteredPage } from "@/components/ui";

export const metadata = { title: "Log in · SocialCommerce" };

export default function LoginPage() {
  return (
    <CenteredPage>
      <LoginForm realm="tenant" title="Log in to your business" />
    </CenteredPage>
  );
}
