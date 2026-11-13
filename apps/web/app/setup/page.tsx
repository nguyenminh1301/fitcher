"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { SetupScreen } from "@/components/setup/SetupScreen";
import { api } from "@/lib/api";

// The first-run setup. A user who is not signed in is sent to the sign-in page.
export default function SetupPage() {
  const router = useRouter();
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  useEffect(() => {
    void api.auth.current().then((identity) => {
      if (!identity) router.replace("/sign-in");
      else setIsAdmin(identity.roles.includes("admin"));
    }).catch(() => router.replace("/sign-in"));
  }, [router]);
  if (isAdmin === null) return null;
  return <SetupScreen setup={api.setup} models={api.models} isAdmin={isAdmin} onSignedOut={() => router.replace("/sign-in")} onOpenChat={() => router.push("/")} />;
}
