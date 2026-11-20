"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { SetupScreen } from "@/components/setup/SetupScreen";
import { ExposureBanner } from "@/components/ui/ExposureBanner";
import { api } from "@/lib/api";
import { AccessRefused } from "@/lib/api/http/auth";
import { keepQuestion } from "@/lib/chat/pendingQuestion";

const hasPack = async () => Boolean(await api.auth.pack());

// The first-run setup of this personal app; the owner answers every step, signed in when a password is set.
export default function SetupPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  useEffect(() => {
    void api.auth.current().then((identity) => {
      // No identity means the owner password asks for a session first.
      if (!identity) router.replace("/sign-in");
      else setReady(true);
    }).catch((error) => {
      // An address the api refuses outright cannot set fitcher up; the api's reason says what to change.
      if (error instanceof AccessRefused) setRefused(error.reason);
      else setReady(true);
    });
  }, [router]);
  if (refused !== null) return <main style={{ padding: 24 }}><ExposureBanner identity={null} refused={refused} /></main>;
  if (!ready) return null;
  return <SetupScreen setup={api.setup} models={api.models} sources={api.sources} hasPack={hasPack}
    onOpenChat={(question) => { if (question) keepQuestion(question); router.push("/"); }}
    onOpenConsole={(path) => router.push(path ?? "/console")} />;
}
