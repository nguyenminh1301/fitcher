"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { SetupScreen } from "@/components/setup/SetupScreen";
import { api } from "@/lib/api";

const packRoles = async () => (await api.auth.pack())?.roles ?? [];

// The first-run setup of this personal app; the owner answers every step.
export default function SetupPage() {
  const router = useRouter();
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  useEffect(() => {
    void api.auth.current().then((identity) => setIsAdmin(identity?.roles.includes("admin") ?? true)).catch(() => setIsAdmin(true));
  }, []);
  if (isAdmin === null) return null;
  return <SetupScreen setup={api.setup} models={api.models} sources={api.sources} documents={api.documents} packRoles={packRoles}
    isAdmin={isAdmin} onOpenChat={() => router.push("/")} />;
}
