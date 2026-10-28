import { AuthScreen } from "@/components/auth-screen";
import { ChangePasswordForm } from "@/components/password-forms";

export const metadata = { title: "Set your password" };

export default function AdminChangePasswordPage() {
  return (
    <AuthScreen audience="admin">
      <ChangePasswordForm realm="platform" firstLogin />
    </AuthScreen>
  );
}
