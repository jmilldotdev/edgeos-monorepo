"use client"

import { useEffect, useState } from "react"
import useAgent from "@/hooks/useAgent"
import useAuth from "@/hooks/useAuth"
import { pendingSetupStep } from "@/lib/agentService"
import { useCityProvider } from "@/providers/cityProvider"
import AgentGate from "./AgentGate"
import AgentOverview from "./AgentOverview"
import AgentSetup from "./AgentSetup"

export default function AgentPage() {
  const { user } = useAuth()
  const { state } = useAgent()
  const { getCity } = useCityProvider()
  // Decided once per visit: finishing setup mid-flow must not swap the page
  // out from under the Connect step.
  const [mode, setMode] = useState<"setup" | "overview" | null>(null)
  useEffect(() => {
    if (state && mode === null)
      setMode(pendingSetupStep(state) ? "setup" : "overview")
  }, [state, mode])

  if (mode === "setup" && state && user)
    return (
      <AgentSetup
        key={`${user.tenant_id}:${user.id}`}
        state={state}
        userName={[user.first_name, user.last_name].filter(Boolean).join(" ")}
        residence={user.residence ?? ""}
        eventName={getCity()?.name ?? "Edge City"}
        onFinished={() => setMode("overview")}
      />
    )
  return <AgentGate>{(current) => <AgentOverview state={current} />}</AgentGate>
}
