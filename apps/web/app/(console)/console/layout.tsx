"use client";

import { usePathname, useRouter } from "next/navigation";
import { useCallback, type ReactNode } from "react";

import { ConsoleLayout } from "@/components/console/ConsoleLayout";
import { SetupGate } from "@/components/setup/SetupGate";
import { api } from "@/lib/api";
import { ChatProvider } from "@/lib/chat/ChatContext";
import { sectionOf } from "@/lib/console/sections";

// The workspace console shares the chat app's identity and pack; its sections are pages under /console.
export default function ConsoleAppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const signIn = useCallback(() => router.replace("/sign-in"), [router]);
  const signOut = useCallback(() => void api.auth.signOut().then((url) => window.location.assign(url)), []);
  const pathname = usePathname();
  const navigate = useCallback((path: string, options?: { replace: boolean }) => (options?.replace ? router.replace(path) : router.push(path)), [router]);
  const openChat = useCallback(() => router.push("/"), [router]);
  const openConversation = useCallback((id: string | null) => router.push(id ? `/c/${encodeURIComponent(id)}` : "/"), [router]);
  return (
    <ChatProvider api={api} navigate={openConversation} activeId={null} onSignedOut={signIn}>
      <SetupGate api={api} redirect={router.replace}>
        <ConsoleLayout section={sectionOf(pathname)} navigate={navigate} onChat={openChat} onSignOut={signOut}>
          {children}
        </ConsoleLayout>
      </SetupGate>
    </ChatProvider>
  );
}
