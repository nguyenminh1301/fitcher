import { ReviewDetail } from "@/components/console/sections/ReviewSection";

export default async function ReviewItemPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ReviewDetail id={decodeURIComponent(id)} />;
}
