import { AddSourcePage } from "@/components/console/sections/SourceFlows";

export default async function NewSourcePage({ searchParams }: { searchParams: Promise<{ kind?: string }> }) {
  const { kind } = await searchParams;
  return <AddSourcePage kind={kind === "database" ? "database" : "file"} />;
}
