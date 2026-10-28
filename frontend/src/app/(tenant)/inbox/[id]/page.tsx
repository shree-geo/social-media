import { Suspense } from "react";

import { Spinner } from "@/components/ui";

import { Thread } from "./thread";

export default function ConversationPage() {
  return (
    <Suspense fallback={<section className="flex-1"><Spinner /></section>}>
      <Thread />
    </Suspense>
  );
}
