"use client";

import { usePathname, useRouter } from "next/navigation";
import { useCallback, type ReactNode } from "react";

import { ChatLayout } from "@/components/chat/ChatLayout";
import { api } from "@/lib/api";
import { ChatProvider } from "@/lib/chat/ChatContext";

// The chat app keeps its sidebar and streaming answers across conversation pages.
export default function ChatAppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const activeId = pathname.startsWith("/c/") ? decodeURIComponent(pathname.slice(3)) : null;
  const navigate = useCallback((id: string | null) => router.push(id ? `/c/${encodeURIComponent(id)}` : "/"), [router]);
  return (
    <ChatProvider api={api} navigate={navigate} activeId={activeId}>
      <ChatLayout onConsole={() => router.push("/console")} onSignOut={() => router.push("/sign-in")}>
        {children}
      </ChatLayout>
    </ChatProvider>
  );
}
