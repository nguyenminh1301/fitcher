import { ReviewDetail } from "@/components/console/sections/ReviewSection";

export default async function ReviewItemPage({ params }: PageProps<"/console/review/[id]">) {
  const { id } = await params;
  return <ReviewDetail id={decodeURIComponent(id)} />;
}
