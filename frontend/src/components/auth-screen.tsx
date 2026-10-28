import { MessageCircle } from "lucide-react";
import type { ReactNode } from "react";

import { DhakaPattern } from "@/components/dhaka-pattern";
import { brand } from "@/config/brand";

/** Login / password screens: brand panel with the weave pattern, form on the right (stacked on phones). */
export function AuthScreen({ children, audience = "business" }: { children: ReactNode; audience?: "business" | "admin" }) {
  return (
    <main className="grid min-h-dvh grid-rows-[auto_1fr] lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:grid-rows-1">
      <aside className="relative overflow-hidden bg-nav text-nav-ink">
        <DhakaPattern className="absolute inset-y-0 right-0 h-full w-24 lg:w-24" />
        <div className="relative flex h-full flex-col justify-between gap-8 px-6 py-6 pr-20 lg:px-12 lg:py-12 lg:pr-36">
          <div>
            <p className="flex items-center gap-2 text-lg font-semibold">
              <MessageCircle className="size-6" aria-hidden />
              {brand.name}
              {audience === "admin" && <span className="font-normal opacity-75">Admin</span>}
            </p>
            <p className="mt-1 text-sm opacity-80 lg:hidden">{brand.statementNe}</p>
          </div>
          <div className="hidden lg:block">
            <p className="text-3xl leading-tight font-semibold">{brand.statement}</p>
            <p className="mt-3 text-xl opacity-80">{brand.statementNe}</p>
          </div>
          <p className="hidden text-sm opacity-70 lg:block">
            Need help logging in? Call us on {brand.supportPhone}.
          </p>
        </div>
      </aside>
      <section className="flex items-start justify-center px-4 py-10 sm:items-center sm:px-6">
        <div className="w-full max-w-sm">{children}</div>
      </section>
    </main>
  );
}
