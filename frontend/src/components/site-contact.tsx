"use client";

import { Mail, MessageCircle, Phone, type LucideIcon } from "lucide-react";
import Link from "next/link";

import { phoneDigits, useSiteContact } from "@/lib/site-contact";

const LINK = "text-primary underline";

/** Inline "email … or call …" for sentences; falls back to the contact page when nothing is set. */
export function ReachUs({ linkClassName = LINK }: { linkClassName?: string }) {
  const { data } = useSiteContact();
  const email = data?.support_email;
  const phone = data?.support_phone;
  const emailLink = email && (
    <a href={`mailto:${email}`} className={linkClassName}>
      {email}
    </a>
  );
  const phoneLink = phone && (
    <a href={`tel:+${phoneDigits(phone)}`} className={`tabular ${linkClassName}`}>
      {phone}
    </a>
  );
  if (emailLink && phoneLink) {
    return (
      <>
        email {emailLink} or call {phoneLink}
      </>
    );
  }
  if (emailLink) return <>email {emailLink}</>;
  if (phoneLink) return <>call {phoneLink}</>;
  return (
    <>
      use our{" "}
      <Link href="/contact" className={linkClassName}>
        contact page
      </Link>
    </>
  );
}

/** Footer line: phone · email, whichever are set. */
export function ContactLine() {
  const { data } = useSiteContact();
  const parts = [data?.support_phone, data?.support_email].filter(Boolean);
  return parts.length ? <> · {parts.join(" · ")}</> : null;
}

/** Contact page cards: call, WhatsApp, email. */
export function ContactCards() {
  const { data, isPending } = useSiteContact();
  if (isPending) return <div className="h-52" aria-hidden />;
  const phone = data?.support_phone;
  const email = data?.support_email;
  const cards: { icon: LucideIcon; title: string; value: string; href: string; note: string; tone: string }[] = [];
  if (phone) {
    const digits = phoneDigits(phone);
    cards.push({
      icon: Phone,
      title: "Call us",
      value: phone,
      href: `tel:+${digits}`,
      note: "Talk to our team.",
      tone: "bg-primary-soft text-primary",
    });
    cards.push({
      icon: MessageCircle,
      title: "WhatsApp",
      value: phone,
      href: `https://wa.me/${digits}`,
      note: "Message us any time.",
      tone: "bg-success-soft text-whatsapp",
    });
  }
  if (email) {
    cards.push({
      icon: Mail,
      title: "Email",
      value: email,
      href: `mailto:${email}`,
      note: "For account, billing and privacy questions.",
      tone: "bg-attention-soft text-attention-ink",
    });
  }
  if (!cards.length) {
    return (
      <p className="rounded-panel border border-line bg-surface p-6 text-ink-muted">Our contact details will be published here soon.</p>
    );
  }
  return (
    <ul className="grid gap-6 md:grid-cols-3">
      {cards.map(({ icon: Icon, title, value, href, note, tone }) => (
        <li key={title}>
          <a href={href} className="block h-full rounded-panel border border-line bg-surface p-6 transition-colors hover:border-primary">
            <span className={`grid size-12 place-items-center rounded-full ${tone}`}>
              <Icon className="size-6" aria-hidden />
            </span>
            <h2 className="mt-4 text-lg font-semibold text-ink">{title}</h2>
            <p className="tabular mt-1 font-medium break-all text-primary">{value}</p>
            <p className="mt-2 text-sm text-ink-muted">{note}</p>
          </a>
        </li>
      ))}
    </ul>
  );
}
