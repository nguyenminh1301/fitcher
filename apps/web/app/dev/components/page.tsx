import { notFound } from "next/navigation";

import { Gallery } from "./Gallery";

// The shared components in both themes and languages, for development only.
export default function ComponentsPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <Gallery />;
}
