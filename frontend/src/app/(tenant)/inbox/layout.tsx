import { Suspense, type ReactNode } from "react";

import { Spinner } from "@/components/ui";

import { ConversationList } from "./conversation-list";

export const metadata = { title: "Inbox" };

export default function InboxLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-[calc(100dvh-7.5rem)] min-h-0 md:h-dvh">
      <Suspense fallback={<Spinner />}>
        <ConversationList />
      </Suspense>
      {children}
    </div>
  );
}
