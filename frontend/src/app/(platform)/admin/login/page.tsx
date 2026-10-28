import { AuthScreen } from "@/components/auth-screen";
import { LoginForm } from "@/components/password-forms";

export const metadata = { title: "Admin login" };

export default function AdminLoginPage() {
  return (
    <AuthScreen audience="admin">
      <LoginForm realm="platform" title="Admin login" intro="Set up businesses, packages and subscriptions." />
    </AuthScreen>
  );
}
