import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback } from "react"
import { AgentService, type AgentState } from "@/lib/agentService"

const AGENT_KEY = ["agent", "setup"] as const

/**
 * Server-owned agent setup shared by the sidebar, dashboard and agent pages.
 * Mutations write their response back with `setState`, so every surface
 * reflects the latest revision without refetching.
 */
export default function useAgent() {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: AGENT_KEY,
    queryFn: AgentService.get,
    staleTime: 30_000,
    retry: 1,
  })
  const setState = useCallback(
    (next: AgentState) => queryClient.setQueryData(AGENT_KEY, next),
    [queryClient],
  )
  const refetch = query.refetch
  return {
    state: query.data ?? null,
    error: query.error,
    isLoading: query.isLoading,
    setState,
    refetch,
  }
}
