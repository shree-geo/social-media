import { Suspense } from "react";

import { Spinner } from "@/components/ui";

import { OrderDetail } from "./order-detail";

export default function OrderPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <OrderDetail />
    </Suspense>
  );
}
