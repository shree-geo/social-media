"use client";

import { useQuery } from "@tanstack/react-query";

/** Support phone and email, set by a super admin in the admin console (Settings). */
export type SiteContact = { support_phone: string | null; support_email: string | null };

export function useSiteContact() {
  return useQuery({
    queryKey: ["site-contact"],
    queryFn: async (): Promise<SiteContact> => {
      const response = await fetch("/api/v1/public/site");
      if (!response.ok) throw new Error(`site contact ${response.status}`);
      return response.json();
    },
    staleTime: 5 * 60_000,
  });
}

/** "+977 985-1234567" → "9779851234567" for tel: and wa.me links. */
export function phoneDigits(phone: string): string {
  return phone.replace(/\D/g, "");
}
