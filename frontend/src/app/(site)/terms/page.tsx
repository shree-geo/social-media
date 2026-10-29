import Link from "next/link";
import type { ReactNode } from "react";

import { LegalLayout, LegalSection, PageIntro } from "@/components/site";
import { ReachUs } from "@/components/site-contact";
import { brand } from "@/config/brand";

export const metadata = { title: "Terms of service" };

/** Public terms of service (Meta app settings link here). Keep subscription wording in step with
 * backend/app/services/subscriptions.py (trial, grace, suspension). */
const UPDATED = "29 October 2026";

const SECTIONS = [
  { id: "agreement", title: "Agreement" },
  { id: "the-service", title: "The service" },
  { id: "accounts", title: "Accounts" },
  { id: "packages-and-payment", title: "Packages and payment" },
  { id: "acceptable-use", title: "Acceptable use" },
  { id: "your-data", title: "Your data" },
  { id: "facebook-and-whatsapp", title: "Facebook and WhatsApp" },
  { id: "availability", title: "Availability and changes" },
  { id: "ending", title: "Ending the service" },
  { id: "liability", title: "Liability" },
  { id: "law", title: "Governing law" },
  { id: "changes", title: "Changes to these terms" },
  { id: "contact", title: "Contact us" },
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

export default function TermsPage() {
  return (
    <>
      <PageIntro eyebrow="Legal" title="Terms of service">
        <p>These terms apply to every business that uses {brand.name} and to the staff who log in for it.</p>
        <p className="mt-3 text-sm">Last updated {UPDATED}</p>
      </PageIntro>
      <LegalLayout sections={SECTIONS}>
        <LegalSection id="agreement" title="Agreement">
          <p>
            By using {brand.name} ({brand.website}) your business agrees to these terms and to our{" "}
            <Link href="/privacy" className="text-primary underline">
              privacy policy
            </Link>
            . The person who accepts them on behalf of the business confirms they are allowed to do so.
          </p>
        </LegalSection>

        <LegalSection id="the-service" title="The service">
          <p>
            {brand.name} lets a business answer Facebook Messenger and WhatsApp chats in one inbox, keep customer records, create orders and
            invoices, and record payments and deliveries. Payments and deliveries are records the business enters; {brand.name} does not
            move money or deliver goods.
          </p>
        </LegalSection>

        <LegalSection id="accounts" title="Accounts">
          <List
            items={[
              "We create each business account and send the owner a temporary password, which must be changed at first login.",
              "The owner decides which staff get access and what each role can do, and is responsible for what staff do in the account.",
              "Keep passwords private and tell us straight away if you think an account has been misused.",
            ]}
          />
        </LegalSection>

        <LegalSection id="packages-and-payment" title="Packages and payment">
          <List
            items={[
              "Each business subscribes to a package. The package sets the price, how often it is paid and limits such as staff logins, products or connected Pages.",
              "Prices are in Nepali rupees and are agreed when the account is created or renewed.",
              "If a renewal is not paid by its due date the account may enter a short grace period and then be suspended until payment is made. Suspension does not delete your data.",
              "Fees already paid are not refunded for unused time unless we agree otherwise in writing.",
            ]}
          />
        </LegalSection>

        <LegalSection id="acceptable-use" title="Acceptable use">
          <p>You agree not to use {brand.name} to:</p>
          <List
            items={[
              "send spam, or message people who have not contacted your business or agreed to hear from it;",
              "sell anything illegal in Nepal, or break Meta's or WhatsApp's commerce and messaging policies;",
              "harass, mislead or defraud anyone;",
              "try to access other businesses' data, overload the service or get around its security or package limits.",
            ]}
          />
          <p>We may suspend an account that breaks these rules, and will tell the owner why.</p>
        </LegalSection>

        <LegalSection id="your-data" title="Your data">
          <p>
            Your business owns its chats, customer records, orders, invoices and other data. We store and process it only to run the service
            for you, as described in the privacy policy. You are responsible for having the right to collect and use your customers&apos;
            information.
          </p>
        </LegalSection>

        <LegalSection id="facebook-and-whatsapp" title="Facebook and WhatsApp">
          <p>
            Connecting a Facebook Page or WhatsApp number uses Meta&apos;s services, which have their own terms. Meta can change or limit
            those services, for example message windows, templates or fees, and we cannot control that. If Meta blocks or disconnects a Page
            or number, messages through it stop until it is reconnected.
          </p>
        </LegalSection>

        <LegalSection id="availability" title="Availability and changes">
          <p>
            We work to keep {brand.name} available and to protect your data, but the service is provided as it is and may sometimes be
            unavailable for maintenance or reasons outside our control. We may improve or change features; we will tell businesses before
            removing something they rely on.
          </p>
        </LegalSection>

        <LegalSection id="ending" title="Ending the service">
          <List
            items={[
              "You can stop using the service at any time by telling us. Your account stays usable until the end of the period already paid.",
              "We can end an account for serious or repeated breaches of these terms, or for non-payment after suspension.",
              "Before an account is closed we can give you an export of your data on request. Afterwards it is deleted or anonymised as described in the privacy policy.",
            ]}
          />
        </LegalSection>

        <LegalSection id="liability" title="Liability">
          <p>
            We are not responsible for lost sales, lost profits or other indirect losses, or for problems caused by Meta, internet or mobile
            providers, or how the service is used. As far as the law allows, our total responsibility for any claim is limited to the fees
            your business paid us in the 12 months before the claim.
          </p>
        </LegalSection>

        <LegalSection id="law" title="Governing law">
          <p>These terms are governed by the laws of Nepal.</p>
        </LegalSection>

        <LegalSection id="changes" title="Changes to these terms">
          <p>If we change these terms we will update the date above and tell businesses about important changes before they apply.</p>
        </LegalSection>

        <LegalSection id="contact" title="Contact us">
          <p>
            Questions about these terms? Please <ReachUs />.
          </p>
        </LegalSection>
      </LegalLayout>
    </>
  );
}
