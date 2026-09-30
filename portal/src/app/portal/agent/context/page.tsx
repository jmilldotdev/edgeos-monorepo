"use client"

import { Check, Loader2 } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import useAgent from "@/hooks/useAgent"
import {
  AgentService,
  type AgentState,
  agentError,
  hasContext,
} from "@/lib/agentService"
import { useCityProvider } from "@/providers/cityProvider"
import AgentGate, { AgentPageHeader } from "../AgentGate"
import ContextForm from "../ContextForm"

export default function AgentContextPage() {
  return <AgentGate>{(state) => <Editor state={state} />}</AgentGate>
}

function Editor({ state }: { state: AgentState }) {
  const { setState } = useAgent()
  const { getCity } = useCityProvider()
  const [draft, setDraft] = useState(state.draft)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [saved, setSaved] = useState(false)
  const dirty = JSON.stringify(draft) !== JSON.stringify(state.draft)
  const canSave = (dirty || state.contextPending) && hasContext(draft)

  async function save() {
    setSaving(true)
    setError("")
    setSaved(false)
    try {
      const next = dirty
        ? await AgentService.save(state.revision, draft)
        : state
      const synced = next.contextPending
        ? await AgentService.sync(next.revision)
        : next
      setState(synced)
      setDraft(synced.draft)
      setSaved(!synced.hostError)
      if (synced.hostError) setError(agentError({ message: synced.hostError }))
    } catch (e) {
      setError(
        e && typeof e === "object" && "status" in e && e.status === 409
          ? "This changed in another tab. Reload to get the latest before saving."
          : agentError(e),
      )
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mx-auto flex min-h-full max-w-3xl flex-col px-4 sm:px-8">
      <div className="flex-1 space-y-8 py-6 sm:py-10">
        <AgentPageHeader
          title="About you"
          lead="Everything your agent knows about you. Start a new conversation after saving so it picks up the changes."
        />
        <ContextForm
          draft={draft}
          onChange={(next) => {
            setDraft(next)
            setSaved(false)
          }}
          eventName={getCity()?.name ?? "Edge City"}
          guided={false}
        />
      </div>
      <footer className="sticky bottom-0 -mx-4 flex flex-wrap items-center gap-3 border-t bg-background/95 px-4 py-3 backdrop-blur sm:-mx-8 sm:px-8">
        <p role="status" className="mr-auto text-sm text-muted-foreground">
          {error ? (
            <span className="text-destructive">{error}</span>
          ) : saved ? (
            <span className="inline-flex items-center gap-1">
              <Check className="size-4" aria-hidden="true" /> Your agent has the
              latest
            </span>
          ) : dirty ? (
            "Unsaved changes"
          ) : state.contextPending ? (
            "Saved, not yet sent to your agent"
          ) : (
            "Up to date"
          )}
        </p>
        {dirty && (
          <Button
            variant="ghost"
            disabled={saving}
            onClick={() => setDraft(state.draft)}
          >
            Discard
          </Button>
        )}
        <Button size="lg" disabled={!canSave || saving} onClick={save}>
          {saving && (
            <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" />
          )}
          Save
        </Button>
      </footer>
    </div>
  )
}
