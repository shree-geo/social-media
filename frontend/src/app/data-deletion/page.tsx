import { brand } from "@/config/brand";

export const metadata = { title: "Data deletion" };

/** Status page Meta links to after a data deletion request (required for app review). */
export default function DataDeletionPage() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="text-2xl font-semibold text-ink">Your data deletion request</h1>
      <p className="mt-4 text-ink">
        We received your request through Facebook. We have removed your Facebook user ID from {brand.name} and stopped
        receiving messages from any Page you connected with it.
      </p>
      <p className="mt-4 text-ink-muted">
        Keep the confirmation code from the link you followed. If you have questions, call us on {brand.supportPhone}.
      </p>
    </main>
  );
}
