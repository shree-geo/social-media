import { Dashboard } from "./dashboard";

export const metadata = { title: "Home" };

export default function DashboardPage() {
  return (
    <main className="px-4 py-6 sm:px-8 sm:py-8">
      <Dashboard />
    </main>
  );
}
