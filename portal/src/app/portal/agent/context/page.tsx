"use client"

import { Check, Loader2 } from "lucide-react"
import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import useAgent from "@/hooks/useAgent"
import {
  AgentService,
  type AgentState,
  agentError,
  CONSENT_BRIEF,
  hasContext,
} from "@/lib/agentService"
import { useCityProvider } from "@/providers/cityProvider"
import AgentGate, { AgentPageHeader } from "../AgentGate"
import ConsentChoices from "../ConsentChoices"
import ContextForm from "../ContextForm"

export default function AgentContextPage() {
  return <AgentGate>{(state) => <Editor state={state} />}</AgentGate>
}

/** Everything personal about the agent: what it knows and research choices. */
function Editor({ state }: { state: AgentState }) {
  const { setState } = useAgent()
  const { getCity } = useCityProvider()
  const [draft, setDraft] = useState(state.draft)
  const [research, setResearch] = useState(state.consent.research)
  const [training, setTraining] = useState(state.consent.training)
  const [busy, setBusy] = useState<"" | "save" | "reset">("")
  const [error, setError] = useState("")
  const [saved, setSaved] = useState(false)
  const draftDirty = JSON.stringify(draft) !== JSON.stringify(state.draft)
  const consentDirty =
    research !== state.consent.research || training !== state.consent.training
  // Links such as the overview's "Manage" land on #privacy; the section only
  // exists after state loads, so the browser's own hash scroll misses it.
  useEffect(() => {
    if (window.location.hash === "#privacy")
      document.getElementById("privacy")?.scrollIntoView()
  }, [])
  const dirty = draftDirty || consentDirty
  const canSave = (dirty || state.contextPending) && hasContext(draft)
  const edited = () => {
    setSaved(false)
    setError("")
  }

  async function save() {
    setBusy("save")
    setError("")
    setSaved(false)
    try {
      let next = state
      if (consentDirty)
        next = await AgentService.consent(
          next.revision,
          research,
          training,
          CONSENT_BRIEF,
        )
      if (draftDirty) next = await AgentService.save(next.revision, draft)
      if (next.contextPending || next.hostError)
        next = await AgentService.sync(next.revision)
      setState(next)
      setDraft(next.draft)
      setSaved(!next.hostError)
      if (next.hostError) setError(agentError({ message: next.hostError }))
    } catch (e) {
      setError(
        e && typeof e === "object" && "status" in e && e.status === 409
          ? "This changed in another tab. Reload to get the latest before saving."
          : agentError(e),
      )
    } finally {
      setBusy("")
    }
  }

  async function startOver() {
    if (
      !window.confirm(
        "Start setup over? Your answers and consent are cleared; your agent and connections stay.",
      )
    )
      return
    setBusy("reset")
    setError("")
    try {
      setState(await AgentService.reset(state.revision))
    } catch (e) {
      setError(agentError(e))
      setBusy("")
    }
  }

  return (
    <div className="mx-auto flex min-h-full max-w-3xl flex-col px-4 sm:px-8">
      <div className="flex-1 space-y-12 py-6 sm:py-10">
        <AgentPageHeader
          title="About you"
          lead="What your agent knows about you and how your data is used. Start a new conversation after saving so it picks up the changes."
        />
        <ContextForm
          draft={draft}
          onChange={(next) => {
            setDraft(next)
            edited()
          }}
          eventName={getCity()?.name ?? "Edge City"}
          guided={false}
        />

        <section id="privacy" className="scroll-mt-20 space-y-5">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">Privacy</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Withdrawing never deletes your agent or affects your ticket.
            </p>
          </div>
          <ConsentChoices
            research={research}
            training={training}
            onResearch={(value) => {
              setResearch(value)
              edited()
            }}
            onTraining={(value) => {
              setTraining(value)
              edited()
            }}
          />
          <div className="rounded-2xl border border-destructive/30 p-5">
            <h3 className="font-medium">Start setup over</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Clears your answers and research consent, then walks you through
              setup again. Your agent, its history and your connections are
              kept.
            </p>
            <Button
              variant="outline"
              className="mt-4"
              disabled={!!busy}
              onClick={startOver}
            >
              {busy === "reset" && (
                <Loader2
                  className="mr-2 size-4 animate-spin"
                  aria-hidden="true"
                />
              )}
              Start over
            </Button>
          </div>
        </section>
      </div>
      <footer className="sticky bottom-0 -mx-4 flex flex-wrap items-center gap-3 border-t bg-background/95 px-4 py-3 backdrop-blur sm:-mx-8 sm:px-8">
        <p role="status" className="mr-auto text-sm text-muted-foreground">
          {busy === "save" ? (
            "Saving and sending to your agent…"
          ) : error ? (
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
            disabled={!!busy}
            onClick={() => {
              setDraft(state.draft)
              setResearch(state.consent.research)
              setTraining(state.consent.training)
            }}
          >
            Discard
          </Button>
        )}
        <Button size="lg" disabled={!canSave || !!busy} onClick={save}>
          {busy === "save" && (
            <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" />
          )}
          Save
        </Button>
      </footer>
    </div>
  )
}
