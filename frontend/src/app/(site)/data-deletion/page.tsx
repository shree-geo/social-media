import Link from "next/link";

import { PageIntro } from "@/components/site";
import { ReachUs } from "@/components/site-contact";
import { brand } from "@/config/brand";

export const metadata = { title: "Data deletion" };

/** Status page Meta links to after a data deletion request (required for app review). */
export default function DataDeletionPage() {
  return (
    <>
      <PageIntro eyebrow="Legal" title="Your data deletion request">
        We received your request through Facebook.
      </PageIntro>
      <section className="mx-auto grid max-w-3xl gap-4 px-4 py-12 text-lg leading-relaxed text-ink sm:px-6">
        <p>We have removed your Facebook user ID from {brand.name} and stopped receiving messages from any Page you connected with it.</p>
        <p className="text-ink-muted">
          Keep the confirmation code from the link you followed. If you have questions, <ReachUs />. Read more in our{" "}
          <Link href="/privacy" className="text-primary underline">
            privacy policy
          </Link>
          .
        </p>
      </section>
    </>
  );
}
