import { PageIntro } from "@/components/site";
import { ContactCards } from "@/components/site-contact";
import { brand } from "@/config/brand";

export const metadata = { title: `Contact us · ${brand.name}` };

const NEXT = [
  "Tell us your business name, what you sell and which Facebook Page and WhatsApp number you use.",
  "We help you choose a package and create your account.",
  "You get your login, set your password and connect your channels with our help.",
];

export default function ContactPage() {
  return (
    <>
      <PageIntro eyebrow="Contact us" title="Let's get your business set up">
        Want to use {brand.name}, or need help with your account? Reach us the way that suits you.
      </PageIntro>

      <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <ContactCards />

        <div className="mt-12 grid gap-8 rounded-panel border border-line bg-surface p-6 sm:p-10 lg:grid-cols-[1fr_1.4fr]">
          <div>
            <h2 className="text-2xl font-bold text-ink">Starting with {brand.name}</h2>
            <p className="mt-2 text-ink-muted">There&apos;s no sign-up form: we set up every account ourselves so it works from day one.</p>
          </div>
          <ol className="grid gap-4">
            {NEXT.map((text, i) => (
              <li key={text} className="flex items-start gap-4">
                <span className="tabular grid size-8 shrink-0 place-items-center rounded-full bg-primary font-bold text-on-primary">
                  {i + 1}
                </span>
                <span className="pt-1 text-ink">{text}</span>
              </li>
            ))}
          </ol>
        </div>
      </section>
    </>
  );
}
