import { AuthScreen } from "@/components/auth-screen";
import { ChangePasswordForm } from "@/components/password-forms";

export const metadata = { title: "Set your password" };

export default function ChangePasswordPage() {
  return (
    <AuthScreen>
      <ChangePasswordForm realm="tenant" firstLogin />
    </AuthScreen>
  );
}
