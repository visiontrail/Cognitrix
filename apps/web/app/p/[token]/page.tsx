import { PublicPageClient } from "@/components/public/public-page-client";

export default async function PublicPublishedPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <PublicPageClient token={token} />;
}
