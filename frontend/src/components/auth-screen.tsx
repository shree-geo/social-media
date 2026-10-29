import { MessagesSquare, ShoppingBag, Truck, Wallet, type LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { BrandMark } from "@/components/brand-mark";
import { ReachUs } from "@/components/site-contact";
import { brand } from "@/config/brand";

/** What the product does, in the order a sale happens. */
const FLOW: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: MessagesSquare, title: "One inbox", text: "Facebook Messenger and WhatsApp chats together." },
  { icon: ShoppingBag, title: "Chat to order", text: "Turn a conversation into an order and invoice." },
  { icon: Wallet, title: "Payments", text: "Cash, eSewa, Khalti, bank transfer and COD." },
  { icon: Truck, title: "Deliveries", text: "Send, track and collect cash on delivery." },
];

/** Login / password screens: brand panel with what the product does, form on the right (stacked on phones). */
export function AuthScreen({ children, audience = "business" }: { children: ReactNode; audience?: "business" | "admin" }) {
  return (
    <main className="grid min-h-dvh grid-rows-[auto_1fr] lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:grid-rows-1">
      <aside className="bg-nav text-nav-ink">
        <div className="flex h-full flex-col justify-between gap-10 px-6 py-6 lg:px-12 lg:py-12">
          <div>
            <p className="flex items-center gap-2 text-lg font-semibold">
              <BrandMark className="size-9 ring-1 ring-nav-line" />
              {brand.name}
              {audience === "admin" && <span className="font-normal opacity-75">Admin</span>}
            </p>
            <p className="mt-1 text-sm opacity-80 lg:hidden">{brand.statementNe}</p>
          </div>
          <div className="hidden lg:block">
            <p className="text-3xl leading-tight font-semibold">{brand.statement}</p>
            <p className="mt-3 text-xl opacity-80">{brand.statementNe}</p>
            <ol className="mt-10 grid gap-5">
              {FLOW.map(({ icon: Icon, title, text }) => (
                <li key={title} className="flex items-start gap-4">
                  <span className="grid size-10 shrink-0 place-items-center rounded-control bg-nav-marker text-nav">
                    <Icon className="size-5" aria-hidden />
                  </span>
                  <span>
                    <span className="block font-semibold">{title}</span>
                    <span className="block text-sm opacity-75">{text}</span>
                  </span>
                </li>
              ))}
            </ol>
          </div>
          <p className="hidden text-sm opacity-70 lg:block">
            Need help logging in? Please <ReachUs linkClassName="underline hover:opacity-100" />. ·{" "}
            <Link href="/privacy" className="underline hover:opacity-100">
              Privacy policy
            </Link> ·{" "}
            <Link href="/terms" className="underline hover:opacity-100">
              Terms
            </Link>
          </p>
        </div>
      </aside>
      <section className="flex items-start justify-center px-4 py-10 sm:items-center sm:px-6">
        <div className="w-full max-w-sm">{children}</div>
      </section>
    </main>
  );
}
