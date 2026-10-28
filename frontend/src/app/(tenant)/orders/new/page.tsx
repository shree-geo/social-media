import { Suspense } from "react";

import { Spinner } from "@/components/ui";

import { OrderForm } from "./order-form";

export const metadata = { title: "New order" };

export default function NewOrderPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <OrderForm />
    </Suspense>
  );
}
