"use client";

import { usePathname, useRouter } from "next/navigation";
import { useCallback, type ReactNode } from "react";

import { ChatLayout } from "@/components/chat/ChatLayout";
import { SetupGate } from "@/components/setup/SetupGate";
import { api } from "@/lib/api";
import { ChatProvider } from "@/lib/chat/ChatContext";
import { useSignOut } from "@/lib/chat/useSignOut";

// The chat app keeps its sidebar and streaming answers across conversation pages.
export default function ChatAppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const signIn = useCallback(() => router.replace("/sign-in"), [router]);
  const signOutNow = useSignOut(api.auth.signOut);
  const signOut = useCallback(() => void signOutNow(), [signOutNow]);
  const pathname = usePathname();
  const activeId = pathname.startsWith("/c/") ? decodeURIComponent(pathname.slice(3)) : null;
  const navigate = useCallback((id: string | null) => router.push(id ? `/c/${encodeURIComponent(id)}` : "/"), [router]);
  return (
    <ChatProvider api={api} navigate={navigate} activeId={activeId} onSignedOut={signIn}>
      <SetupGate api={api} redirect={router.replace}>
        <ChatLayout onConsole={() => router.push("/console")} onSignOut={signOut}>
          {children}
        </ChatLayout>
      </SetupGate>
    </ChatProvider>
  );
}
