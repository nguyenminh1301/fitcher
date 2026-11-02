import { RunDetail } from "@/components/console/sections/RunsSection";

export default async function RunTracePage({ params }: { params: Promise<{ traceId: string }> }) {
  const { traceId } = await params;
  return <RunDetail traceId={decodeURIComponent(traceId)} />;
}
