"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { SetupScreen } from "@/components/setup/SetupScreen";
import { api } from "@/lib/api";
import { keepQuestion } from "@/lib/chat/pendingQuestion";

const hasPack = async () => Boolean(await api.auth.pack());

// The first-run setup of this personal app; the owner answers every step, signed in when a password is set.
export default function SetupPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    void api.auth.current().then((identity) => {
      // No identity means the owner password asks for a session first.
      if (!identity) router.replace("/sign-in");
      else setReady(true);
    }).catch(() => setReady(true));
  }, [router]);
  if (!ready) return null;
  return <SetupScreen setup={api.setup} models={api.models} sources={api.sources} hasPack={hasPack}
    onOpenChat={(question) => { if (question) keepQuestion(question); router.push("/"); }}
    onOpenConsole={(path) => router.push(path ?? "/console")} />;
}
