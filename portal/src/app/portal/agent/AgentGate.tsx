"use client"

import { Loader2 } from "lucide-react"
import { useRouter } from "next/navigation"
import { useEffect } from "react"
import { Button } from "@/components/ui/button"
import useAgent from "@/hooks/useAgent"
import {
  type AgentState,
  agentError,
  pendingSetupStep,
} from "@/lib/agentService"

/** Loads agent state; sends participants who haven't finished setup to it. */
export default function AgentGate({
  children,
}: {
  children: (state: AgentState) => React.ReactNode
}) {
  const router = useRouter()
  const { state, error, refetch } = useAgent()
  const needsSetup = state ? pendingSetupStep(state) !== null : false
  useEffect(() => {
    if (needsSetup) router.replace("/portal/agent")
  }, [needsSetup, router])

  if (error)
    return (
      <div role="alert" className="mx-auto max-w-md p-8 text-center">
        <p className="text-sm">{agentError(error)}</p>
        <Button variant="outline" className="mt-4" onClick={() => refetch()}>
          Try again
        </Button>
      </div>
    )
  if (!state || needsSetup)
    return (
      <div role="status" className="flex justify-center py-24">
        <Loader2
          className="size-6 animate-spin text-muted-foreground motion-reduce:animate-none"
          aria-label="Loading"
        />
      </div>
    )
  return <>{children(state)}</>
}

export function AgentPageHeader({
  title,
  lead,
  children,
}: {
  title: string
  lead?: string
  children?: React.ReactNode
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <p className="text-sm font-medium text-primary">Agent Village</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">{title}</h1>
        {lead && <p className="mt-2 max-w-2xl text-muted-foreground">{lead}</p>}
      </div>
      {children}
    </header>
  )
}
