import { MessagesSquare } from "lucide-react";

import { EmptyState } from "@/components/ui";

export default function InboxHome() {
  return (
    <section className="hidden flex-1 items-center justify-center md:flex">
      <EmptyState icon={MessagesSquare} title="Choose a chat">
        Pick a conversation on the left to read it and reply.
      </EmptyState>
    </section>
  );
}
