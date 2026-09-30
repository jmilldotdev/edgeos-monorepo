"use client"

import {
  ArrowLeft,
  ArrowRight,
  Handshake,
  Loader2,
  ShieldCheck,
  UsersRound,
} from "lucide-react"
import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import useAgent from "@/hooks/useAgent"
import {
  type AgentDraft,
  AgentService,
  type AgentState,
  agentError,
  CONSENT_BRIEF,
  hasContext,
  pendingSetupStep,
} from "@/lib/agentService"
import { cn } from "@/lib/utils"
import ConsentChoices from "./ConsentChoices"
import ContextForm from "./ContextForm"
import DesktopPanel from "./DesktopPanel"
import TelegramPanel from "./TelegramPanel"

type Step = "intro" | "consent" | "about" | "connect"
const STEPS: { id: Step; label: string }[] = [
  { id: "intro", label: "The experiment" },
  { id: "consent", label: "Consent" },
  { id: "about", label: "About you" },
  { id: "connect", label: "Connect" },
]

const COPY: Record<Step, { title: string; lead: string }> = {
  intro: {
    title: "Meet your agent",
    lead: "Everyone in the village gets a personal AI agent that works on their behalf. Setup takes about ten minutes.",
  },
  consent: {
    title: "Your consent",
    lead: "Agent Village is a live research experiment. Here’s what that means for you.",
  },
  about: {
    title: "Tell your agent about you",
    lead: "Your agent is only as useful as what it knows. The quickest way to give it something rich is to ask an AI that already knows you.",
  },
  connect: {
    title: "Say hello on Telegram",
    lead: "Telegram is where you’ll talk to your agent and where it will check with you before acting.",
  },
}

export default function AgentSetup({
  state,
  userName,
  residence,
  eventName,
  onFinished,
}: {
  state: AgentState
  userName: string
  residence: string
  eventName: string
  onFinished: () => void
}) {
  const { setState, refetch } = useAgent()
  const [step, setStep] = useState<Step>(
    () => pendingSetupStep(state) ?? "connect",
  )
  const [draft, setDraft] = useState<AgentDraft>(() => ({
    ...state.draft,
    profile: {
      ...state.draft.profile,
      name: state.draft.profile.name || userName,
      basedIn: state.draft.profile.basedIn || residence,
    },
  }))
  const [research, setResearch] = useState(state.consent.research)
  const [training, setTraining] = useState(state.consent.training)
  const [busy, setBusy] = useState("")
  const [error, setError] = useState("")
  const [conflict, setConflict] = useState(false)

  const index = STEPS.findIndex((s) => s.id === step)
  const go = (next: Step) => {
    setStep(next)
    setError("")
    document.getElementById("portal-scroll")?.scrollTo({ top: 0 })
  }

  async function act(label: string, work: () => Promise<void>) {
    setBusy(label)
    setError("")
    try {
      await work()
    } catch (e) {
      if (e && typeof e === "object" && "status" in e && e.status === 409) {
        setConflict(true)
        setError(
          "Your setup changed in another tab. Your edits are still here; reload the latest before continuing.",
        )
      } else setError(agentError(e))
    } finally {
      setBusy("")
    }
  }

  const agentStatus = state.agent?.status
  const [waitedOut, setWaitedOut] = useState(false)
  // Poll while the runtime starts; stop after two minutes.
  useEffect(() => {
    if (step !== "connect" || agentStatus !== "creating") return
    setWaitedOut(false)
    const started = Date.now()
    const timer = window.setInterval(async () => {
      const { data } = await refetch()
      if (data?.agent?.status !== "creating") window.clearInterval(timer)
      else if (Date.now() - started > 120_000) {
        window.clearInterval(timer)
        setWaitedOut(true)
      }
    }, 3000)
    return () => window.clearInterval(timer)
  }, [step, agentStatus, refetch])

  const primary: Record<
    Step,
    { label: string; disabled?: boolean; hint?: string; run: () => void }
  > = {
    intro: { label: "Get started", run: () => go("consent") },
    consent: {
      label: "Agree and continue",
      disabled: !research,
      hint: research ? undefined : "Research consent is required for an agent",
      run: () =>
        act("Saving…", async () => {
          setState(
            await AgentService.consent(
              state.revision,
              research,
              training,
              CONSENT_BRIEF,
            ),
          )
          go("about")
        }),
    },
    about: {
      label: state.agent ? "Save and continue" : "Create my agent",
      disabled: !hasContext(draft) || !draft.profile.name.trim() || conflict,
      hint: hasContext(draft) ? undefined : "Add a few sentences to continue",
      run: () =>
        act(state.agent ? "Saving…" : "Creating your agent…", async () => {
          const saved = await AgentService.save(state.revision, draft)
          setState(saved)
          setState(
            saved.agent
              ? saved.contextPending
                ? await AgentService.sync(saved.revision)
                : saved
              : await AgentService.provision(saved.revision),
          )
          go("connect")
        }),
    },
    connect: {
      label: "Go to my agent",
      disabled: agentStatus !== "ready",
      run: onFinished,
    },
  }
  const action = primary[step]

  return (
    <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col px-4 sm:px-8">
      <header className="pt-6 sm:pt-10">
        <ol className="grid grid-cols-4 gap-1.5" aria-label="Setup progress">
          {STEPS.map((s, i) => (
            <li key={s.id} aria-current={i === index ? "step" : undefined}>
              <span
                className={cn(
                  "block h-1 rounded-full",
                  i <= index ? "bg-primary" : "bg-muted",
                )}
              />
              <span
                className={cn(
                  "mt-2 hidden text-xs sm:block",
                  i === index
                    ? "font-medium text-foreground"
                    : "text-muted-foreground",
                )}
              >
                {s.label}
              </span>
            </li>
          ))}
        </ol>
        <p className="mt-6 text-sm font-medium text-primary sm:hidden">
          Step {index + 1} of {STEPS.length} · {STEPS[index].label}
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:mt-8 sm:text-4xl">
          {COPY[step].title}
        </h1>
        <p className="mt-3 max-w-2xl text-base leading-relaxed text-muted-foreground sm:text-lg">
          {COPY[step].lead}
        </p>
      </header>

      <div className="flex-1 py-8">
        {error && (
          <div
            role="alert"
            className="mb-6 rounded-xl border border-destructive/40 bg-destructive/5 p-4 text-sm"
          >
            <p className="break-words">{error}</p>
            {conflict && (
              <Button
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={() =>
                  act("Loading…", async () => {
                    const latest = await AgentService.get()
                    setState(latest)
                    setDraft(latest.draft)
                    setConflict(false)
                  })
                }
              >
                Load the latest
              </Button>
            )}
          </div>
        )}

        {step === "intro" && <Intro />}
        {step === "consent" && (
          <ConsentChoices
            research={research}
            training={training}
            onResearch={setResearch}
            onTraining={setTraining}
          />
        )}
        {step === "about" && (
          <ContextForm
            draft={draft}
            onChange={setDraft}
            eventName={eventName}
          />
        )}
        {step === "connect" && (
          <div className="space-y-6">
            <RuntimeStatus
              state={state}
              waitedOut={waitedOut}
              onRetry={() =>
                act("Starting…", async () => {
                  setState(await AgentService.provision(state.revision))
                })
              }
              onCheck={() => {
                setWaitedOut(false)
                void refetch()
              }}
            />
            {agentStatus === "ready" && (
              <>
                <section className="rounded-2xl border bg-card p-5 sm:p-6">
                  <h2 className="text-lg font-semibold">Telegram</h2>
                  <p className="mb-5 mt-1 text-sm text-muted-foreground">
                    You’ll create a private bot that only you can talk to.
                    Telegram opens, you tap Create, and this page picks it up.
                  </p>
                  <TelegramPanel
                    disabled={!!busy}
                    pairingId={state.telegramPairingId}
                  />
                </section>
                <section className="rounded-2xl border bg-card px-5 sm:px-6">
                  <DesktopPanel />
                </section>
              </>
            )}
          </div>
        )}
      </div>

      <footer className="sticky bottom-0 -mx-4 flex items-center gap-3 border-t bg-background/95 px-4 py-3 backdrop-blur sm:-mx-8 sm:px-8">
        {index > 0 && step !== "connect" && (
          <Button
            variant="ghost"
            disabled={!!busy}
            onClick={() => go(STEPS[index - 1].id)}
          >
            <ArrowLeft className="mr-1 size-4" aria-hidden="true" />
            Back
          </Button>
        )}
        {action.hint && !busy && (
          <span className="ml-auto hidden text-sm text-muted-foreground sm:inline">
            {action.hint}
          </span>
        )}
        <Button
          size="lg"
          className={cn("ml-auto px-6", action.hint && "sm:ml-0")}
          disabled={action.disabled || !!busy}
          onClick={action.run}
        >
          {busy ? (
            <>
              <Loader2
                className="mr-2 size-4 animate-spin motion-reduce:animate-none"
                aria-hidden="true"
              />
              {busy}
            </>
          ) : (
            <>
              {action.label}
              {step !== "connect" && (
                <ArrowRight className="ml-2 size-4" aria-hidden="true" />
              )}
            </>
          )}
        </Button>
      </footer>
    </div>
  )
}

function Intro() {
  const points = [
    {
      icon: UsersRound,
      title: "Finds your people",
      body: "Reads the village for collaborators and kindred spirits who match what you’re here for.",
    },
    {
      icon: Handshake,
      title: "Handles the logistics",
      body: "Talks to other residents’ agents to propose introductions and find times that work.",
    },
    {
      icon: ShieldCheck,
      title: "Asks before it acts",
      body: "Nothing consequential happens without your OK. Pause or reset it anytime.",
    },
  ]
  return (
    <div className="space-y-8">
      <ul className="grid gap-3 sm:grid-cols-3">
        {points.map((p) => (
          <li key={p.title} className="rounded-2xl border bg-card p-5">
            <p.icon className="size-6 text-primary" aria-hidden="true" />
            <p className="mt-4 font-semibold">{p.title}</p>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
              {p.body}
            </p>
          </li>
        ))}
      </ul>
      <div className="space-y-2">
        <p className="text-sm font-medium">What you’ll do</p>
        <ol className="space-y-2 text-sm text-muted-foreground">
          <li>1. Read the research terms and choose what you agree to</li>
          <li>2. Describe yourself, ideally with help from your own AI</li>
          <li>3. Connect Telegram so you can talk to your agent</li>
        </ol>
        <p className="pt-2 text-sm text-muted-foreground">
          Progress saves as you go, on any device.
        </p>
      </div>
    </div>
  )
}

function RuntimeStatus({
  state,
  waitedOut,
  onRetry,
  onCheck,
}: {
  state: AgentState
  waitedOut: boolean
  onRetry: () => void
  onCheck: () => void
}) {
  const status = state.agent?.status
  if (status === "ready") return null
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex flex-col items-center rounded-2xl border bg-card px-6 py-12 text-center"
    >
      {status === "failed" ? (
        <>
          <p className="text-lg font-semibold">Your agent didn’t start</p>
          {state.agent?.error && (
            <p className="mt-2 break-words text-sm text-muted-foreground">
              {agentError({ message: state.agent.error })}
            </p>
          )}
          <Button className="mt-5" onClick={onRetry}>
            Try again
          </Button>
        </>
      ) : (
        <>
          {!waitedOut && (
            <Loader2
              className="size-8 animate-spin text-primary motion-reduce:animate-none"
              aria-hidden="true"
            />
          )}
          <p className="mt-4 text-lg font-semibold">
            {waitedOut ? "Still waking up" : "Waking your agent up…"}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {waitedOut
              ? "This is taking longer than usual."
              : "Usually under a minute."}
          </p>
          {waitedOut && (
            <Button variant="outline" className="mt-5" onClick={onCheck}>
              Check again
            </Button>
          )}
        </>
      )}
    </div>
  )
}
