import { ConversationView } from "@/components/chat/ConversationView";

export default async function ConversationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ConversationView id={decodeURIComponent(id)} />;
}
