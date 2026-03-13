import RunHydrator from '@/components/RunHydrator';

export default async function RunLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  return <RunHydrator runId={runId}>{children}</RunHydrator>;
}
