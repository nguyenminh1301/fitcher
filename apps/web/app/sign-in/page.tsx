import { SignInScreen } from "@/components/chat/SignInScreen";

export default async function SignInPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return <SignInScreen failed={error === "sign_in_failed"} />;
}
