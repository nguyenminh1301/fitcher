"use client";

import { usePathname, useRouter } from "next/navigation";
import { useCallback, type ReactNode } from "react";

import { ChatLayout } from "@/components/chat/ChatLayout";
import { api } from "@/lib/api";
import { ChatProvider } from "@/lib/chat/ChatContext";

// The chat app keeps its sidebar and streaming answers across conversation pages.
export default function ChatAppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const signIn = useCallback(() => router.replace("/sign-in"), [router]);
  const signOut = useCallback(() => void api.auth.signOut().then((url) => window.location.assign(url)), []);
  const pathname = usePathname();
  const activeId = pathname.startsWith("/c/") ? decodeURIComponent(pathname.slice(3)) : null;
  const navigate = useCallback((id: string | null) => router.push(id ? `/c/${encodeURIComponent(id)}` : "/"), [router]);
  return (
    <ChatProvider api={api} navigate={navigate} activeId={activeId} onSignedOut={signIn}>
      <ChatLayout onConsole={() => router.push("/console")} onSignOut={signOut}>
        {children}
      </ChatLayout>
    </ChatProvider>
  );
}
