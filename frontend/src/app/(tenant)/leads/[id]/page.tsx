import { Suspense } from "react";

import { Spinner } from "@/components/ui";

import { LeadDetail } from "./lead-detail";

export const metadata = { title: "Lead" };

export default function LeadPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <LeadDetail />
    </Suspense>
  );
}
