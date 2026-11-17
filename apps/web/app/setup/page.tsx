"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { SetupScreen } from "@/components/setup/SetupScreen";
import { api } from "@/lib/api";
import { keepQuestion } from "@/lib/chat/pendingQuestion";

const packRoles = async () => (await api.auth.pack())?.roles ?? [];

// The first-run setup of this personal app; the owner answers every step, signed in when a password is set.
export default function SetupPage() {
  const router = useRouter();
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  useEffect(() => {
    void api.auth.current().then((identity) => {
      // No identity means the owner password asks for a session first.
      if (!identity) router.replace("/sign-in");
      else setIsAdmin(identity.roles.includes("admin"));
    }).catch(() => setIsAdmin(true));
  }, [router]);
  if (isAdmin === null) return null;
  return <SetupScreen setup={api.setup} models={api.models} sources={api.sources} documents={api.documents} packRoles={packRoles}
    isAdmin={isAdmin} onOpenChat={(question) => { if (question) keepQuestion(question); router.push("/"); }} />;
}
