import { Suspense } from "react";

import { Spinner } from "@/components/ui";

import { CustomerProfile } from "./customer-360";

export default function CustomerPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <CustomerProfile />
    </Suspense>
  );
}
