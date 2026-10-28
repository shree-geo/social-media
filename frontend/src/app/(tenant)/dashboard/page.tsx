import { Dashboard } from "./dashboard";

export const metadata = { title: "Dashboard · SocialCommerce" };

export default function DashboardPage() {
  return (
    <main className="flex flex-1 px-4 py-8">
      <Dashboard />
    </main>
  );
}
