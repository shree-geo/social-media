import { CheckCircle2, ShoppingBag, Truck } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { ContactBand, PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/site";
import { CallLine } from "@/components/site-contact";
import { brand } from "@/config/brand";

export const metadata = {
  title: `${brand.name} · Sell from Facebook and WhatsApp chats`,
};

const PROOF = [
  { lead: "Rupees", rest: "with eSewa, Khalti, Fonepay and cash on delivery" },
  { lead: "13% VAT", rest: "bills, numbered by Nepali fiscal year" },
  { lead: "Nepali and English", rest: "for staff and customers" },
  { lead: "Any phone", rest: "your staff and riders already carry" },
];

const STEPS = [
  { title: "We create your account", text: "Tell us about your business. We set up your account and send your login." },
  { title: "Connect your Page and WhatsApp", text: "A guided setup links your Facebook Page and WhatsApp number in about 20 minutes." },
  { title: "Start selling from chats", text: "Reply, take orders, record payments and send deliveries, from a computer or a phone." },
];

/* Hero: the sale as it happens. Plays once on load; still for anyone who has turned motion off. */

function Bubble({ from, children, meta, delay }: { from: "customer" | "shop"; children: ReactNode; meta: string; delay: string }) {
  const shop = from === "shop";
  return (
    <div
      className={
        "story-in max-w-[85%] rounded-bubble px-3.5 py-2 text-sm " +
        (shop ? "ml-auto rounded-br-md bg-primary text-on-primary" : "rounded-bl-md border border-line bg-surface text-ink")
      }
      style={{ animationDelay: delay }}
    >
      {children}
      <span className={"mt-0.5 block text-right text-[0.7rem] " + (shop ? "text-on-primary/75" : "text-ink-subtle")}>{meta}</span>
    </div>
  );
}

function SaleStory() {
  return (
    <div className="relative mx-auto grid w-full max-w-md gap-2.5" aria-label="A customer asks about a sofa on Messenger, pays an advance by eSewa, and the order goes out for delivery.">
      <Bubble from="customer" meta="Messenger, 2:14 PM" delay="0.1s">
        Is the 3-seater sofa available in grey?
      </Bubble>
      <Bubble from="shop" meta="2:16 PM" delay="0.6s">
        Yes! Rs. 44,500 with delivery inside Kathmandu.
      </Bubble>
      <Bubble from="customer" meta="2:17 PM" delay="1.1s">
        I&apos;ll take it. Paying advance by eSewa.
      </Bubble>
      <div className="story-in mt-1 grid gap-2 rounded-panel border border-dashed border-line-strong bg-surface p-4 text-sm shadow-lg" style={{ animationDelay: "1.7s" }}>
        <p className="flex items-center justify-between gap-2">
          <span className="tabular flex items-center gap-2 font-semibold text-ink">
            <ShoppingBag className="size-4 text-primary" aria-hidden />
            ORD-2083-84-000042
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-stage-out-soft px-2.5 py-0.5 text-xs font-semibold text-stage-out">
            <span className="size-1.5 rounded-full bg-current" aria-hidden />
            Out for delivery
          </span>
        </p>
        <p className="tabular flex items-center justify-between gap-2 text-ink-muted">
          <span className="flex items-center gap-2">
            <CheckCircle2 className="size-4 text-success" aria-hidden />
            Received by eSewa
          </span>
          Rs. 10,000
        </p>
        <p className="flex items-center justify-between gap-2 border-t border-line pt-2 text-ink">
          <span className="flex items-center gap-2">
            <Truck className="size-4 text-stage-out" aria-hidden />
            Collect on delivery
          </span>
          <span className="figure text-xl">Rs. 34,500</span>
        </p>
      </div>
    </div>
  );
}

/* Feature pictures: small, true-to-the-product views of the app. */

function InboxPicture() {
  const rows = [
    { initials: "HT", name: "Hari Thapa", text: "Payment eSewa bata garna milchha?", wait: "42m", channel: "bg-whatsapp" },
    { initials: "SR", name: "Sita Rai", text: "Do you have 4 feet tables in black?", wait: "1h", channel: "bg-messenger" },
    { initials: "BK", name: "Bikash KC", text: "Photo pathaunus na sofa ko", wait: null, channel: "bg-whatsapp" },
  ];
  return (
    <div className="overflow-hidden rounded-panel border border-line bg-surface shadow-lg" aria-hidden>
      {rows.map((r, i) => (
        <div key={r.name} className={"flex items-center gap-3 px-4 py-3 " + (i ? "border-t border-line" : "bg-primary-soft")}>
          <span className="relative grid size-10 shrink-0 place-items-center rounded-full bg-sunken text-sm font-semibold text-ink-muted">
            {r.initials}
            <span className={`absolute -right-0.5 -bottom-0.5 size-3.5 rounded-full ring-2 ring-surface ${r.channel}`} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block font-semibold text-ink">{r.name}</span>
            <span className="block truncate text-sm text-ink-muted">{r.text}</span>
          </span>
          {r.wait && <span className="tabular rounded-full bg-attention-soft px-2 text-xs font-semibold text-attention-ink">{r.wait}</span>}
        </div>
      ))}
    </div>
  );
}

function BillPicture() {
  return (
    <div className="tabular rounded-panel border border-line bg-surface p-5 text-sm shadow-lg" aria-hidden>
      <div className="flex items-center justify-between gap-3">
        <span className="font-semibold text-ink">INV-2083-84-000117</span>
        <span className="text-xs text-ink-muted">PAN 601234567</span>
      </div>
      <div className="mt-4 grid grid-cols-[1fr_auto] gap-x-4 gap-y-2 text-ink-muted">
        <span className="text-ink">Teak Sofa Set, 3+1+1</span>
        <span className="text-ink">45,000</span>
        <span>Discount</span>
        <span>− 500</span>
        <span>VAT 13%, included</span>
        <span>5,119</span>
      </div>
      <div className="mt-3 flex items-baseline justify-between border-t-2 border-ink pt-3">
        <span className="font-semibold text-ink">Total</span>
        <span className="figure text-2xl text-ink">Rs. 44,500</span>
      </div>
    </div>
  );
}

function MoneyPicture() {
  const stages = [
    { label: "Confirmed", n: 4, className: "bg-stage-confirmed-soft text-stage-confirmed" },
    { label: "Ready", n: 2, className: "bg-stage-ready-soft text-stage-ready" },
    { label: "Out for delivery", n: 3, className: "bg-stage-out-soft text-stage-out" },
  ];
  return (
    <div className="grid gap-3" aria-hidden>
      <div className="grid grid-cols-3 gap-2">
        {stages.map((s) => (
          <div key={s.label} className={`rounded-panel px-3 py-3 ${s.className}`}>
            <p className="truncate text-xs font-semibold">{s.label}</p>
            <p className="figure text-2xl text-ink">{s.n}</p>
          </div>
        ))}
      </div>
      <div className="rounded-panel border border-attention bg-surface p-4 shadow-[inset_4px_0_0_var(--sc-attention)]">
        <p className="text-sm text-ink-muted">To collect from 3 riders today</p>
        <p className="figure mt-1 text-3xl text-ink">Rs. 1,02,500</p>
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-sunken">
          <div className="h-full w-2/5 rounded-full bg-stage-done" />
        </div>
      </div>
    </div>
  );
}

const FEATURES: { title: string; text: string; points: string[]; picture: ReactNode }[] = [
  {
    title: "Every chat in one list",
    text: "Facebook Messenger and WhatsApp chats arrive together. You see who has waited longest, and the customer's orders and dues sit beside the chat.",
    points: ["Give chats to staff", "Sort chats as lead, support or spam", "Customer history, even across two apps"],
    picture: <InboxPicture />,
  },
  {
    title: "From chat to order to bill",
    text: "Turn a conversation into an order with products, prices and discounts, then make a VAT bill with your PAN, numbered for the fiscal year.",
    points: ["Products with prices and stock", "Bilingual PDF bills", "Bills lock once they're issued"],
    picture: <BillPicture />,
  },
  {
    title: "Deliveries and money, in step",
    text: "Send orders with your own riders or a courier. Record eSewa, Khalti, Fonepay, bank and cash on delivery, and always know who still owes you.",
    points: ["Riders update status from their phone", "Cash collected at the door is recorded", "Payments are never edited, only voided with a reason"],
    picture: <MoneyPicture />,
  },
];

export default function HomePage() {
  return (
    <>
      <style>{`
        @media (prefers-reduced-motion: no-preference) {
          .story-in { animation: story-in 0.45s ease-out both; }
          @keyframes story-in { from { opacity: 0.001; transform: translateY(8px); } to { opacity: 1; transform: none; } }
        }
      `}</style>
      <section className="overflow-hidden">
        <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 py-14 sm:px-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:py-20">
          <div className="min-w-0">
            <p className="inline-flex items-center gap-2 text-sm text-ink-muted">
              <span className="size-2 rounded-full bg-whatsapp" aria-hidden />
              Made in Nepal for shops that sell on WhatsApp and Facebook
            </p>
            <h1 className="font-display mt-4 text-5xl leading-[1.02] font-semibold text-ink sm:text-6xl">{brand.statement}</h1>
            <p className="font-display mt-3 text-2xl font-medium text-ink-muted sm:text-3xl">{brand.statementNe}</p>
            <p className="mt-6 max-w-xl text-lg text-ink-muted">
              Your customers already message you. {brand.name} turns those chats into orders, bills, deliveries and payments, so nothing gets
              lost in a phone.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link href="/contact" className={PRIMARY_BUTTON}>
                Talk to us
              </Link>
              <Link href="/login" className={SECONDARY_BUTTON}>
                Log in
              </Link>
              <CallLine className="text-sm text-ink-muted" />
            </div>
          </div>
          <SaleStory />
        </div>
      </section>

      <section className="border-y border-line bg-surface" aria-label="Built for how Nepal sells">
        <ul className="mx-auto grid max-w-6xl gap-x-8 gap-y-3 px-4 py-6 text-ink-muted sm:grid-cols-2 sm:px-6 lg:grid-cols-4">
          {PROOF.map((p) => (
            <li key={p.lead}>
              <strong className="font-semibold text-ink">{p.lead}</strong> {p.rest}
            </li>
          ))}
        </ul>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-20">
        <div className="max-w-2xl">
          <h2 className="font-display text-4xl leading-tight font-semibold text-ink">Everything after &ldquo;Is this available?&rdquo;</h2>
          <p className="mt-3 text-lg text-ink-muted">From the first message to cash in hand, every step of a sale in one app.</p>
        </div>
        <div className="mt-12 grid gap-16">
          {FEATURES.map((f, i) => (
            <article key={f.title} className="grid items-center gap-8 lg:grid-cols-2 lg:gap-16">
              <div className={"min-w-0 " + (i % 2 ? "lg:order-2" : "")}>
                <h3 className="font-display text-3xl font-semibold text-ink">{f.title}</h3>
                <p className="mt-3 max-w-xl text-lg text-ink-muted">{f.text}</p>
                <ul className="mt-5 grid gap-2">
                  {f.points.map((point) => (
                    <li key={point} className="flex items-start gap-2.5 text-ink">
                      <CheckCircle2 className="mt-1 size-4 shrink-0 text-primary" aria-hidden />
                      {point}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="min-w-0">{f.picture}</div>
            </article>
          ))}
        </div>
      </section>

      <section className="border-y border-line bg-surface">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <h2 className="font-display text-4xl font-semibold text-ink">How it works</h2>
          <ol className="mt-10 grid gap-10 md:grid-cols-3">
            {STEPS.map((step, i) => (
              <li key={step.title} className="border-t-2 border-primary pt-4">
                <span className="figure text-3xl text-primary">{i + 1}</span>
                <h3 className="mt-2 text-lg font-semibold text-ink">{step.title}</h3>
                <p className="mt-1.5 text-ink-muted">{step.text}</p>
              </li>
            ))}
          </ol>
          <p className="mt-10 text-ink-muted">Owners, sales staff, accountants and riders each see only what they need.</p>
        </div>
      </section>

      <ContactBand />
    </>
  );
}
