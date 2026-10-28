import { AuthScreen } from "@/components/auth-screen";
import { LoginForm } from "@/components/password-forms";

export const metadata = { title: "Log in" };

export default function LoginPage() {
  return (
    <AuthScreen>
      <LoginForm realm="tenant" title="Log in" intro="Reply to customers and manage orders from one place." />
    </AuthScreen>
  );
}
