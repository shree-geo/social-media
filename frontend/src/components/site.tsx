import { Menu } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { BrandMark } from "@/components/brand-mark";
import { ContactLine } from "@/components/site-contact";
import { brand } from "@/config/brand";

/** Public website (home, about, contact, legal): header, footer and shared building blocks. */

const NAV = [
  { href: "/", label: "Home" },
  { href: "/about", label: "About us" },
  { href: "/contact", label: "Contact us" },
] as const;

const BUTTON = "inline-flex min-h-11 items-center justify-center gap-2 rounded-control px-5 font-semibold transition-colors";
export const PRIMARY_BUTTON = `${BUTTON} bg-primary text-on-primary hover:bg-primary-hover`;
export const SECONDARY_BUTTON = `${BUTTON} border border-line-strong bg-surface text-ink hover:bg-sunken`;
export const MARIGOLD_BUTTON = `${BUTTON} bg-nav-marker text-nav hover:opacity-90`;

function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2 text-lg font-semibold text-ink">
      <BrandMark className="size-9" />
      {brand.name}
    </Link>
  );
}

function SiteHeader() {
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-paper/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Logo />
        <nav aria-label="Site" className="hidden items-center gap-1 md:flex">
          {NAV.map((item) => (
            <Link key={item.href} href={item.href} className="rounded-control px-3 py-2 text-ink-muted hover:bg-sunken hover:text-ink">
              {item.label}
            </Link>
          ))}
          <Link href="/login" className={`${PRIMARY_BUTTON} ml-3 min-h-10 px-4`}>
            Log in
          </Link>
        </nav>
        {/* Phone menu without JavaScript. */}
        <details className="group relative md:hidden">
          <summary className="grid size-11 cursor-pointer list-none place-items-center rounded-control text-ink hover:bg-sunken [&::-webkit-details-marker]:hidden">
            <Menu className="size-6" aria-hidden />
            <span className="sr-only">Menu</span>
          </summary>
          <nav
            aria-label="Site"
            className="absolute right-0 mt-2 grid w-56 gap-1 rounded-panel border border-line bg-surface p-2 shadow-lg"
          >
            {NAV.map((item) => (
              <Link key={item.href} href={item.href} className="rounded-control px-3 py-2.5 text-ink hover:bg-sunken">
                {item.label}
              </Link>
            ))}
            <Link href="/login" className={`${PRIMARY_BUTTON} mt-1`}>
              Log in
            </Link>
          </nav>
        </details>
      </div>
    </header>
  );
}

function SiteFooter() {
  const columns = [
    {
      title: "Product",
      links: [
        { href: "/", label: "Home" },
        { href: "/login", label: "Log in" },
      ],
    },
    {
      title: "Company",
      links: [
        { href: "/about", label: "About us" },
        { href: "/contact", label: "Contact us" },
      ],
    },
    {
      title: "Legal",
      links: [
        { href: "/privacy", label: "Privacy policy" },
        { href: "/terms", label: "Terms of service" },
        { href: "/data-deletion", label: "Data deletion" },
      ],
    },
  ];
  return (
    <footer className="bg-nav text-nav-ink">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-12 sm:px-6 md:grid-cols-[2fr_1fr_1fr_1fr]">
        <div>
          <p className="flex items-center gap-2 text-lg font-semibold">
            <BrandMark className="size-8 ring-1 ring-nav-line" />
            {brand.name}
          </p>
          <p className="mt-2 max-w-xs text-nav-ink-muted">{brand.statement}</p>
          <p className="mt-1 text-nav-ink-muted">{brand.statementNe}</p>
        </div>
        {columns.map((col) => (
          <div key={col.title}>
            <p className="text-sm font-semibold tracking-wide text-nav-marker uppercase">{col.title}</p>
            <ul className="mt-3 grid gap-2">
              {col.links.map((link) => (
                <li key={link.href}>
                  <Link href={link.href} className="text-nav-ink-muted hover:text-nav-ink">
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-nav-line">
        <p className="mx-auto max-w-6xl px-4 py-5 text-sm text-nav-ink-muted sm:px-6">
          © {brand.name}
          <ContactLine />
        </p>
      </div>
    </footer>
  );
}

export function SiteShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-paper">
      <SiteHeader />
      <main className="flex-1">{children}</main>
      <SiteFooter />
    </div>
  );
}

/** Title band at the top of inner pages. */
export function PageIntro({ eyebrow, title, children }: { eyebrow: string; title: string; children?: ReactNode }) {
  return (
    <section className="border-b border-line bg-surface">
      <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 sm:py-16">
        <p className="text-sm font-semibold tracking-wide text-primary uppercase">{eyebrow}</p>
        <h1 className="mt-2 max-w-3xl text-3xl leading-tight font-bold text-ink sm:text-4xl">{title}</h1>
        {children && <div className="mt-4 max-w-2xl text-lg text-ink-muted">{children}</div>}
      </div>
    </section>
  );
}

/** Call to action band shared by every page. */
export function ContactBand() {
  return (
    <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
      <div className="flex flex-col items-start justify-between gap-6 rounded-panel bg-nav px-6 py-10 text-nav-ink sm:px-10 md:flex-row md:items-center">
        <div>
          <h2 className="text-2xl font-bold">Ready to sell from your chats?</h2>
          <p className="mt-2 text-nav-ink-muted">We set up your account and help you connect Facebook and WhatsApp.</p>
        </div>
        <Link href="/contact" className={MARIGOLD_BUTTON}>
          Talk to us
        </Link>
      </div>
    </section>
  );
}

/** Legal pages: table of contents beside the text on wide screens. */
export function LegalLayout({ sections, children }: { sections: { id: string; title: string }[]; children: ReactNode }) {
  return (
    <div className="mx-auto grid max-w-6xl gap-10 px-4 py-12 sm:px-6 lg:grid-cols-[14rem_minmax(0,1fr)]">
      <nav aria-label="On this page" className="hidden lg:block">
        <div className="sticky top-24">
          <p className="text-sm font-semibold text-ink">On this page</p>
          <ul className="mt-3 grid gap-2 border-l border-line text-sm">
            {sections.map((s) => (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  className="-ml-px block border-l border-transparent pl-4 text-ink-muted hover:border-primary hover:text-ink"
                >
                  {s.title}
                </a>
              </li>
            ))}
          </ul>
        </div>
      </nav>
      <article className="max-w-3xl leading-relaxed text-ink">{children}</article>
    </div>
  );
}

export function LegalSection({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-24 border-b border-line py-8 first:pt-0 last:border-b-0">
      <h2 className="text-xl font-semibold text-ink">{title}</h2>
      <div className="mt-3 grid gap-3">{children}</div>
    </section>
  );
}
