import { EvaluationReport } from "@/components/console/sections/EvaluationSection";

export default async function EvaluationReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EvaluationReport id={decodeURIComponent(id)} />;
}
