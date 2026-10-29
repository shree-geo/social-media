import { HandHeart, Lock, MapPin, Smartphone, type LucideIcon } from "lucide-react";

import { ContactBand, PageIntro } from "@/components/site";
import { brand } from "@/config/brand";

export const metadata = { title: `About us · ${brand.name}` };

const VALUES: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: MapPin,
    title: "Nepal first",
    text: "Rupees, local wallets, VAT invoices and the Nepali fiscal year are built in, not added later.",
  },
  {
    icon: Smartphone,
    title: "Phone friendly",
    text: "Owners and riders work from their phones, so every screen works on a small one.",
  },
  {
    icon: HandHeart,
    title: "We set you up",
    text: "We create your account and walk you through connecting Facebook and WhatsApp.",
  },
  {
    icon: Lock,
    title: "Your data stays yours",
    text: "Each business's data is kept separate and is never sold or used for advertising.",
  },
];

export default function AboutPage() {
  return (
    <>
      <PageIntro eyebrow="About us" title="We help small businesses sell from their chats">
        In Nepal, a lot of selling happens in Facebook Messenger and WhatsApp. We build the tool that keeps those sales organised.
      </PageIntro>

      <section className="mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 lg:grid-cols-2">
        <div>
          <h2 className="text-2xl font-bold text-ink">Why we built {brand.name}</h2>
          <div className="mt-4 grid gap-4 text-lg text-ink-muted">
            <p>
              A furniture shop, a clothing page or a home bakery can get dozens of messages a day. Orders are written in notebooks, payments
              are checked against screenshots, and deliveries are tracked in someone&apos;s head. When a staff member is away, customers
              wait.
            </p>
            <p>
              {brand.name} brings it together: one inbox for every chat, a customer&apos;s full history on one screen, orders and invoices
              made from the conversation, and payments and deliveries that update as they happen.
            </p>
          </div>
        </div>
        <blockquote className="self-start rounded-panel bg-nav p-8 text-nav-ink">
          <p className="text-2xl leading-snug font-semibold">{brand.statement}</p>
          <p className="mt-3 text-lg text-nav-ink-muted">{brand.statementNe}</p>
        </blockquote>
      </section>

      <section className="border-y border-line bg-surface">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <h2 className="text-2xl font-bold text-ink">What we care about</h2>
          <ul className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {VALUES.map(({ icon: Icon, title, text }) => (
              <li key={title}>
                <span className="grid size-11 place-items-center rounded-control bg-primary-soft text-primary">
                  <Icon className="size-5" aria-hidden />
                </span>
                <h3 className="mt-4 font-semibold text-ink">{title}</h3>
                <p className="mt-1.5 text-ink-muted">{text}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <ContactBand />
    </>
  );
}
