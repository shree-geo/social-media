import { Suspense } from "react";

import { Spinner } from "@/components/ui";

import { LeadsView } from "./leads-view";

export const metadata = { title: "Leads" };

export default function LeadsPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <LeadsView />
    </Suspense>
  );
}
