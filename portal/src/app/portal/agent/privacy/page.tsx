"use client"

import { Loader2 } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import useAgent from "@/hooks/useAgent"
import {
  AgentService,
  type AgentState,
  agentError,
  CONSENT_BRIEF,
} from "@/lib/agentService"
import AgentGate, { AgentPageHeader } from "../AgentGate"
import ConsentChoices from "../ConsentChoices"

export default function AgentPrivacyPage() {
  return <AgentGate>{(state) => <Privacy state={state} />}</AgentGate>
}

function Privacy({ state }: { state: AgentState }) {
  const { setState } = useAgent()
  const [research, setResearch] = useState(state.consent.research)
  const [training, setTraining] = useState(state.consent.training)
  const [busy, setBusy] = useState<"" | "consent" | "reset">("")
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  )
  const changed =
    research !== state.consent.research || training !== state.consent.training

  async function run(kind: "consent" | "reset", work: () => Promise<string>) {
    setBusy(kind)
    setMessage(null)
    try {
      setMessage({ ok: true, text: await work() })
    } catch (e) {
      setMessage({ ok: false, text: agentError(e) })
    } finally {
      setBusy("")
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-10 px-4 py-6 sm:px-8 sm:py-10">
      <AgentPageHeader
        title="Privacy"
        lead="Your research choices. Withdrawing never deletes your agent or affects your ticket."
      />
      <section className="space-y-5">
        <ConsentChoices
          research={research}
          training={training}
          onResearch={setResearch}
          onTraining={setTraining}
        />
        <div className="flex flex-wrap items-center gap-3">
          <Button
            disabled={!changed || !!busy}
            onClick={() =>
              run("consent", async () => {
                const next = await AgentService.consent(
                  state.revision,
                  research,
                  training,
                  CONSENT_BRIEF,
                )
                setState(next)
                return next.hostError
                  ? "Saved. Your agent hasn’t received the change yet; apply it from the overview."
                  : "Choices saved."
              })
            }
          >
            {busy === "consent" && (
              <Loader2
                className="mr-2 size-4 animate-spin"
                aria-hidden="true"
              />
            )}
            Save choices
          </Button>
          {message && (
            <p
              role={message.ok ? "status" : "alert"}
              className={
                message.ok
                  ? "text-sm text-muted-foreground"
                  : "text-sm text-destructive"
              }
            >
              {message.text}
            </p>
          )}
        </div>
      </section>

      <section className="rounded-2xl border border-destructive/30 p-5 sm:p-6">
        <h2 className="font-semibold">Start setup over</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Clears your setup answers and research consent, then walks you through
          setup again. Your agent, its history and your connections are kept.
        </p>
        <Button
          variant="outline"
          className="mt-4"
          disabled={!!busy}
          onClick={() => {
            if (
              !window.confirm(
                "Start setup over? Your answers and consent are cleared; your agent and connections stay.",
              )
            )
              return
            void run("reset", async () => {
              setState(await AgentService.reset(state.revision))
              return "Setup reset."
            })
          }}
        >
          {busy === "reset" && (
            <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" />
          )}
          Start over
        </Button>
      </section>
    </div>
  )
}
