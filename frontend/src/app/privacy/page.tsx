import Link from "next/link";
import type { ReactNode } from "react";

import { brand } from "@/config/brand";

export const metadata = { title: "Privacy policy" };

/** Public privacy policy (Meta app settings and app review link here). Keep in step with what the app stores:
 * docs/ONBOARDING_AND_CHANNEL_SETUP.md §10. */
const UPDATED = "29 October 2026";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="text-lg font-semibold text-ink">{title}</h2>
      <div className="mt-3 grid gap-3 text-ink">{children}</div>
    </section>
  );
}

function List({ items }: { items: ReactNode[] }) {
  return (
    <ul className="grid list-disc gap-1.5 pl-5">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}

export default function PrivacyPage() {
  const email = (
    <a href={`mailto:${brand.supportEmail}`} className="text-primary underline">
      {brand.supportEmail}
    </a>
  );
  return (
    <main className="mx-auto max-w-2xl px-4 py-12 leading-relaxed">
      <p className="text-sm text-ink-muted">
        <Link href="/login" className="text-primary hover:underline">
          {brand.name}
        </Link>
      </p>
      <h1 className="mt-2 text-3xl font-semibold text-ink">Privacy policy</h1>
      <p className="mt-2 text-sm text-ink-muted">Last updated {UPDATED}</p>

      <p className="mt-6 text-ink">
        {brand.name} ({brand.website}) helps small businesses in Nepal answer Facebook Messenger and WhatsApp chats,
        take orders, issue invoices and record payments and deliveries in one place. This policy explains what
        information we handle, why, and the choices you have.
      </p>

      <Section title="Who this policy covers">
        <List
          items={[
            <>
              <strong>Businesses</strong> that subscribe to {brand.name}, and their staff who log in.
            </>,
            <>
              <strong>People who message those businesses</strong> on Facebook Messenger or WhatsApp. For their
              information we act on the business&apos;s behalf: the business decides what to record about its
              customers, and we store and process it so the business can serve them.
            </>,
          ]}
        />
      </Section>

      <Section title="What we collect">
        <List
          items={[
            <>
              <strong>Business details:</strong> business name, address, phone, email, PAN/VAT number and the package
              it subscribes to.
            </>,
            <>
              <strong>Staff accounts:</strong> name, email, phone number and role. Passwords are stored only as a
              one-way hash.
            </>,
            <>
              <strong>Connected channels:</strong> the Facebook Page or WhatsApp Business number a business connects
              (its ID, name and picture) and the access token Meta issues for it.
            </>,
            <>
              <strong>Conversations:</strong> messages, photos and other attachments exchanged with the business, and
              the sender&apos;s profile name and, for WhatsApp, phone number.
            </>,
            <>
              <strong>Business records:</strong> customers, products, orders, invoices, payments and deliveries that
              the business enters.
            </>,
            <>
              <strong>Security and usage logs:</strong> sign-ins, IP address, browser type and a record of important
              changes, kept to protect accounts and investigate problems.
            </>,
          ]}
        />
      </Section>

      <Section title="What we do not collect">
        <p>
          We never ask for or see a Facebook password. We do not read anyone&apos;s personal timeline, friends list,
          posts or personal messages. We only receive messages sent to the Pages and WhatsApp numbers a business has
          connected.
        </p>
      </Section>

      <Section title="How we use information">
        <List
          items={[
            "To provide the service: show chats in the inbox, send the business's replies, and keep its orders, invoices, payments and deliveries.",
            "To run accounts and subscriptions, and to contact businesses about their account.",
            "To keep the service secure, prevent misuse and fix problems.",
          ]}
        />
        <p>We do not sell personal information and we do not use it for advertising.</p>
      </Section>

      <Section title="Who we share it with">
        <List
          items={[
            "Meta Platforms (Facebook Messenger and WhatsApp), to receive and send messages for connected businesses.",
            "Service providers that host our servers, store files and deliver email, only as needed to run the service.",
            "Authorities, when the law requires it.",
          ]}
        />
        <p>Each business sees only its own data. Staff of one business cannot see another business&apos;s chats or records.</p>
      </Section>

      <Section title="How we protect it">
        <List
          items={[
            "All traffic is encrypted with HTTPS.",
            "Facebook and WhatsApp access tokens are stored encrypted and are never shown to anyone.",
            "Each business's data is kept separate at the database level.",
            "Staff only see what their role allows, and important actions are logged.",
          ]}
        />
      </Section>

      <Section title="How long we keep it">
        <List
          items={[
            "Business data is kept while the business's account is open, so it can see its history.",
            "Raw message notifications from Meta are deleted after 30 days; the messages themselves stay in the business's inbox.",
            "When a business closes its account, we delete or anonymise its data, except records the law requires us or the business to keep, such as invoices.",
          ]}
        />
      </Section>

      <Section title="Your choices">
        <List
          items={[
            <>
              <strong>If you messaged a business:</strong> ask that business to correct or delete your information. You
              can also contact us at {email}.
            </>,
            <>
              <strong>If you connected a Facebook Page:</strong> you can remove {brand.name} in Facebook under Settings
              → Business integrations. Facebook then tells us, and we stop receiving that Page&apos;s messages and
              remove your Facebook user ID. See{" "}
              <Link href="/data-deletion" className="text-primary underline">
                data deletion
              </Link>
              .
            </>,
            <>
              <strong>Staff and business owners:</strong> contact us to see, correct or delete your account information.
            </>,
          ]}
        />
      </Section>

      <Section title="Children">
        <p>{brand.name} is a tool for businesses and is not meant for children under 16.</p>
      </Section>

      <Section title="Changes">
        <p>If we change this policy we will update the date above, and tell businesses about important changes.</p>
      </Section>

      <Section title="Contact us">
        <p>
          Email {email} or call {brand.supportPhone}.
        </p>
      </Section>
    </main>
  );
}
