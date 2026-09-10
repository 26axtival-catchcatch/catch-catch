import { SignalCatcherApp } from "@/features/signal-catcher/SignalCatcherApp";
import type { ViewParam } from "@/features/signal-catcher/state/use-catch-session";

interface RunResultPageProps {
  params: Promise<{ runId: string }>;
  searchParams: Promise<{ view?: string | string[] }>;
}

function resultView(value: string | string[] | undefined): ViewParam {
  return value === "trace" || value === "action" ? value : "result";
}

export default async function RunResultPage({
  params,
  searchParams,
}: RunResultPageProps) {
  const [{ runId }, query] = await Promise.all([params, searchParams]);
  return <SignalCatcherApp initialRunId={runId} initialView={resultView(query.view)} />;
}
