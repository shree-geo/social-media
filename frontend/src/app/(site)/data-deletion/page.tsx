import Link from "next/link";

import { PageIntro } from "@/components/site";
import { ReachUs } from "@/components/site-contact";
import { brand } from "@/config/brand";

export const metadata = { title: "Data deletion" };

/** How to ask for data to be deleted, and where Meta sends people after a deletion request from Facebook
 * (both required for app review). */
export default function DataDeletionPage() {
  return (
    <>
      <PageIntro eyebrow="Legal" title="Deleting your data">
        How to remove your information from {brand.name}.
      </PageIntro>
      <section className="mx-auto grid max-w-3xl gap-10 px-4 py-12 leading-relaxed text-ink sm:px-6">
        <div>
          <h2 className="text-xl font-semibold">If you connected a Facebook Page</h2>
          <ol className="mt-3 grid list-decimal gap-1.5 pl-5">
            <li>On Facebook, open Settings &amp; privacy → Settings → Business integrations.</li>
            <li>
              Find {brand.name} and choose <strong>Remove</strong>.
            </li>
          </ol>
          <p className="mt-3">
            Facebook tells us straight away. We stop receiving messages from any Page you connected, remove your Facebook user ID and give
            you a confirmation code.
          </p>
        </div>

        <div className="rounded-panel border border-success/30 bg-success-soft p-5">
          <h2 className="font-semibold text-ink">Came here from Facebook after removing {brand.name}?</h2>
          <p className="mt-1 text-ink-muted">
            Your request has been received and processed. Keep the confirmation code from the link you followed in case you need to ask us
            about it.
          </p>
        </div>

        <div>
          <h2 className="text-xl font-semibold">If you messaged a business that uses {brand.name}</h2>
          <p className="mt-3">
            The business controls its customer records, so ask it to delete your information. You can also contact us and we will pass your
            request on and confirm when it is done.
          </p>
        </div>

        <div>
          <h2 className="text-xl font-semibold">Business owners and staff</h2>
          <p className="mt-3">
            To close your business account and delete its data, or to remove a staff login, contact us from the email address on the
            account.
          </p>
        </div>

        <p className="text-ink-muted">
          Questions? Please <ReachUs />. Read more in our{" "}
          <Link href="/privacy" className="text-primary underline">
            privacy policy
          </Link>
          .
        </p>
      </section>
    </>
  );
}
