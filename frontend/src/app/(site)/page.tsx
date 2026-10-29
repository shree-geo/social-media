import {
  CheckCircle2,
  FileText,
  Languages,
  MessagesSquare,
  ShoppingBag,
  Smartphone,
  Truck,
  UserRound,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

import { ContactBand, PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/site";
import { brand } from "@/config/brand";

export const metadata = {
  title: `${brand.name} · Sell from Facebook and WhatsApp chats`,
};

const FEATURES: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: MessagesSquare,
    title: "One inbox",
    text: "Facebook Messenger and WhatsApp chats in one list. Assign chats to staff and never miss a customer.",
  },
  {
    icon: UserRound,
    title: "Customer history",
    text: "Every customer's chats, orders and payments on one screen, even when they write from two apps.",
  },
  {
    icon: ShoppingBag,
    title: "Chat to order",
    text: "Turn a conversation into an order in seconds, with products, prices, discounts and delivery address.",
  },
  {
    icon: FileText,
    title: "Invoices with VAT",
    text: "Print or share invoices with your PAN/VAT number, numbered by Nepali fiscal year.",
  },
  {
    icon: Wallet,
    title: "Payments",
    text: "Record cash, eSewa, Khalti, Fonepay, bank transfer and cash on delivery. See who still owes you.",
  },
  {
    icon: Truck,
    title: "Deliveries",
    text: "Send orders with your own riders or a courier. Riders update status and cash collected from their phone.",
  },
];

const STEPS = [
  {
    title: "We create your account",
    text: "Tell us about your business. We set up your account and send your login.",
  },
  {
    title: "Connect your Page and WhatsApp",
    text: "A guided setup links your Facebook Page and WhatsApp number in about 20 minutes.",
  },
  {
    title: "Start selling from chats",
    text: "Reply, take orders, record payments and send deliveries, from a computer or a phone.",
  },
];

const NEPAL = [
  { icon: Wallet, text: "Rupees, eSewa, Khalti, Fonepay and COD" },
  { icon: FileText, text: "13% VAT and Nepali fiscal year numbering" },
  { icon: Languages, text: "Customer names and messages in Nepali" },
  { icon: Smartphone, text: "Works on the phone your staff already use" },
];

/** A small, true-to-the-product picture of a sale moving from chat to delivery. */
function ProductPreview() {
  return (
    <div className="relative mx-auto w-full max-w-md" aria-hidden>
      <div className="rounded-panel border border-line bg-surface p-4 shadow-xl">
        <div className="flex items-center gap-3 border-b border-line pb-3">
          <span className="grid size-10 place-items-center rounded-full bg-primary-soft font-semibold text-primary">SK</span>
          <div className="min-w-0">
            <p className="font-semibold text-ink">Sita Karki</p>
            <p className="text-xs font-medium text-messenger">Messenger</p>
          </div>
        </div>
        <div className="grid gap-2 py-4 text-sm">
          <p className="max-w-[80%] rounded-bubble rounded-bl-md bg-sunken px-3.5 py-2 text-ink">Is the 3-seater sofa available in grey?</p>
          <p className="ml-auto max-w-[80%] rounded-bubble rounded-br-md bg-primary px-3.5 py-2 text-on-primary">
            Yes! Rs. 44,500 with delivery inside Kathmandu.
          </p>
          <p className="max-w-[80%] rounded-bubble rounded-bl-md bg-sunken px-3.5 py-2 text-ink">
            I&apos;ll take it. Paying advance by eSewa.
          </p>
        </div>
        <div className="grid gap-2 rounded-control bg-sunken p-3 text-sm">
          <p className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-2 font-semibold text-ink">
              <ShoppingBag className="size-4 text-primary" />
              ORD-2083-84-000042
            </span>
            <span className="tabular font-semibold text-ink">Rs. 44,500</span>
          </p>
          <p className="flex items-center gap-2 text-ink-muted">
            <CheckCircle2 className="size-4 text-success" />
            Rs. 10,000 received by eSewa
          </p>
          <p className="flex items-center gap-2 text-ink-muted">
            <Truck className="size-4 text-attention-ink" />
            Out for delivery · collect Rs. 34,500
          </p>
        </div>
      </div>
      <div className="absolute -bottom-5 -left-4 hidden items-center gap-2 rounded-full border border-line bg-surface px-4 py-2 text-sm font-medium text-ink shadow-lg sm:flex">
        <span className="size-2.5 rounded-full bg-whatsapp" />3 new WhatsApp chats
      </div>
    </div>
  );
}

export default function HomePage() {
  return (
    <>
      <section className="overflow-hidden">
        <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 py-14 sm:px-6 lg:grid-cols-2 lg:py-24">
          <div>
            <p className="inline-flex items-center gap-2 rounded-full bg-primary-soft px-3 py-1 text-sm font-medium text-primary">
              Made for businesses in Nepal
            </p>
            <h1 className="mt-5 text-4xl leading-tight font-bold text-ink sm:text-5xl">{brand.statement}</h1>
            <p className="mt-3 text-xl text-ink-muted">{brand.statementNe}</p>
            <p className="mt-6 max-w-xl text-lg text-ink-muted">
              Your customers already buy through Facebook and WhatsApp. {brand.name} puts those chats, the orders that come from them,
              payments and deliveries in one place, so nothing gets lost in a phone.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/contact" className={PRIMARY_BUTTON}>
                Talk to us
              </Link>
              <Link href="/login" className={SECONDARY_BUTTON}>
                Log in
              </Link>
            </div>
          </div>
          <ProductPreview />
        </div>
      </section>

      <section className="border-y border-line bg-surface">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <div className="max-w-2xl">
            <h2 className="text-3xl font-bold text-ink">Everything after &ldquo;Is this available?&rdquo;</h2>
            <p className="mt-3 text-lg text-ink-muted">From the first message to cash in hand, every step of a sale in one app.</p>
          </div>
          <ul className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <li key={title} className="rounded-panel border border-line bg-paper p-6">
                <span className="grid size-11 place-items-center rounded-control bg-nav text-nav-marker">
                  <Icon className="size-5" aria-hidden />
                </span>
                <h3 className="mt-4 text-lg font-semibold text-ink">{title}</h3>
                <p className="mt-1.5 text-ink-muted">{text}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <h2 className="text-3xl font-bold text-ink">How it works</h2>
        <ol className="mt-10 grid gap-6 md:grid-cols-3">
          {STEPS.map((step, i) => (
            <li key={step.title} className="relative rounded-panel border border-line bg-surface p-6">
              <span className="tabular grid size-10 place-items-center rounded-full bg-primary text-lg font-bold text-on-primary">
                {i + 1}
              </span>
              <h3 className="mt-4 text-lg font-semibold text-ink">{step.title}</h3>
              <p className="mt-1.5 text-ink-muted">{step.text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="border-y border-line bg-surface">
        <div className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-16 sm:px-6 lg:grid-cols-2">
          <div>
            <h2 className="text-3xl font-bold text-ink">Built for how Nepal sells</h2>
            <p className="mt-3 text-lg text-ink-muted">
              Not a foreign tool translated later. Payments, invoices and numbering work the way Nepali businesses already do.
            </p>
            <p className="mt-6 flex items-center gap-2 text-ink-muted">
              <Users className="size-5 text-primary" aria-hidden />
              Owners, sales staff, accountants and riders each see what they need.
            </p>
          </div>
          <ul className="grid gap-3 sm:grid-cols-2">
            {NEPAL.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-start gap-3 rounded-panel border border-line bg-paper p-4">
                <Icon className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden />
                <span className="font-medium text-ink">{text}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <ContactBand />
    </>
  );
}
