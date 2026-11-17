"use client";

import { useRouter } from "next/navigation";
import { useCallback } from "react";

import { OwnerSignIn } from "@/components/chat/OwnerSignIn";
import { api } from "@/lib/api";

// Signing in with the owner password; the app sends a browser here when the api asks for a session.
export default function SignInPage() {
  const router = useRouter();
  const open = useCallback(() => router.replace("/"), [router]);
  return <OwnerSignIn owner={api.owner} onSignedIn={open} />;
}
