import Link from "next/link";
import type { ReactNode } from "react";

import { LegalLayout, LegalSection, PageIntro } from "@/components/site";
import { ReachUs } from "@/components/site-contact";
import { brand } from "@/config/brand";

export const metadata = { title: "Privacy policy" };

/** Public privacy policy (Meta app settings and app review link here). Keep in step with what the app stores:
 * docs/ONBOARDING_AND_CHANNEL_SETUP.md §10. */
const UPDATED = "29 October 2026";

const SECTIONS = [
  { id: "who-this-policy-covers", title: "Who this policy covers" },
  { id: "what-we-collect", title: "What we collect" },
  { id: "what-we-do-not-collect", title: "What we do not collect" },
  { id: "how-we-use-information", title: "How we use information" },
  { id: "who-we-share-it-with", title: "Who we share it with" },
  { id: "how-we-protect-it", title: "How we protect it" },
  { id: "how-long-we-keep-it", title: "How long we keep it" },
  { id: "your-choices", title: "Your choices" },
  { id: "children", title: "Children" },
  { id: "changes", title: "Changes" },
  { id: "contact-us", title: "Contact us" },
];

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
  return (
    <>
      <PageIntro eyebrow="Legal" title="Privacy policy">
        <p>
          {brand.name} ({brand.website}) helps small businesses in Nepal answer Facebook Messenger and WhatsApp chats, take orders, issue
          invoices and record payments and deliveries in one place. This policy explains what information we handle, why, and the choices
          you have.
        </p>
        <p className="mt-3 text-sm">Last updated {UPDATED}</p>
      </PageIntro>
      <LegalLayout sections={SECTIONS}>
        <LegalSection id="who-this-policy-covers" title="Who this policy covers">
          <List
            items={[
              <>
                <strong>Businesses</strong> that subscribe to {brand.name}, and their staff who log in.
              </>,
              <>
                <strong>People who message those businesses</strong> on Facebook Messenger or WhatsApp. For their information we act on the
                business&apos;s behalf: the business decides what to record about its customers, and we store and process it so the business
                can serve them.
              </>,
            ]}
          />
        </LegalSection>

        <LegalSection id="what-we-collect" title="What we collect">
          <List
            items={[
              <>
                <strong>Business details:</strong> business name, address, phone, email, PAN/VAT number and the package it subscribes to.
              </>,
              <>
                <strong>Staff accounts:</strong> name, email, phone number and role. Passwords are stored only as a one-way hash.
              </>,
              <>
                <strong>Connected channels:</strong> the Facebook Page or WhatsApp Business number a business connects (its ID, name and
                picture) and the access token Meta issues for it.
              </>,
              <>
                <strong>Conversations:</strong> messages, photos and other attachments exchanged with the business, and the sender&apos;s
                profile name and, for WhatsApp, phone number.
              </>,
              <>
                <strong>Business records:</strong> customers, products, orders, invoices, payments and deliveries that the business enters.
              </>,
              <>
                <strong>Security and usage logs:</strong> sign-ins, IP address, browser type and a record of important changes, kept to
                protect accounts and investigate problems.
              </>,
            ]}
          />
        </LegalSection>

        <LegalSection id="what-we-do-not-collect" title="What we do not collect">
          <p>
            We never ask for or see a Facebook password. We do not read anyone&apos;s personal timeline, friends list, posts or personal
            messages. We only receive messages sent to the Pages and WhatsApp numbers a business has connected.
          </p>
        </LegalSection>

        <LegalSection id="how-we-use-information" title="How we use information">
          <List
            items={[
              "To provide the service: show chats in the inbox, send the business's replies, and keep its orders, invoices, payments and deliveries.",
              "To run accounts and subscriptions, and to contact businesses about their account.",
              "To keep the service secure, prevent misuse and fix problems.",
            ]}
          />
          <p>We do not sell personal information and we do not use it for advertising.</p>
        </LegalSection>

        <LegalSection id="who-we-share-it-with" title="Who we share it with">
          <List
            items={[
              "Meta Platforms (Facebook Messenger and WhatsApp), to receive and send messages for connected businesses.",
              "Service providers that host our servers, store files and deliver email, only as needed to run the service.",
              "Authorities, when the law requires it.",
            ]}
          />
          <p>Each business sees only its own data. Staff of one business cannot see another business&apos;s chats or records.</p>
        </LegalSection>

        <LegalSection id="how-we-protect-it" title="How we protect it">
          <List
            items={[
              "All traffic is encrypted with HTTPS.",
              "Facebook and WhatsApp access tokens are stored encrypted and are never shown to anyone.",
              "Each business's data is kept separate at the database level.",
              "Staff only see what their role allows, and important actions are logged.",
            ]}
          />
        </LegalSection>

        <LegalSection id="how-long-we-keep-it" title="How long we keep it">
          <List
            items={[
              "Business data is kept while the business's account is open, so it can see its history.",
              "Raw message notifications from Meta are deleted after 30 days; the messages themselves stay in the business's inbox.",
              "When a business closes its account, we delete or anonymise its data, except records the law requires us or the business to keep, such as invoices.",
            ]}
          />
        </LegalSection>

        <LegalSection id="your-choices" title="Your choices">
          <List
            items={[
              <>
                <strong>If you messaged a business:</strong> ask that business to correct or delete your information. You can also <ReachUs />.
              </>,
              <>
                <strong>If you connected a Facebook Page:</strong> you can remove {brand.name} in Facebook under Settings → Business
                integrations. Facebook then tells us, and we stop receiving that Page&apos;s messages and remove your Facebook user ID. See{" "}
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
        </LegalSection>

        <LegalSection id="children" title="Children">
          <p>{brand.name} is a tool for businesses and is not meant for children under 16.</p>
        </LegalSection>

        <LegalSection id="changes" title="Changes">
          <p>If we change this policy we will update the date above, and tell businesses about important changes.</p>
        </LegalSection>

        <LegalSection id="contact-us" title="Contact us">
          <p>
            Please <ReachUs />.
          </p>
        </LegalSection>
      </LegalLayout>
    </>
  );
}
