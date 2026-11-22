import { BuildPackPage } from "@/components/console/sections/SourceFlows";

export default async function SourceBuildPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <BuildPackPage id={decodeURIComponent(id)} />;
}
