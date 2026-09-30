"use client"

import { useQuery } from "@tanstack/react-query"
import {
  ArrowRight,
  ExternalLink,
  Loader2,
  Monitor,
  NotebookPen,
  Send,
  ShieldCheck,
} from "lucide-react"
import Link from "next/link"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import useAgent from "@/hooks/useAgent"
import {
  AgentService,
  type AgentState,
  agentError,
  publicBotUrl,
  wordCount,
} from "@/lib/agentService"
import { cn } from "@/lib/utils"
import { AgentPageHeader } from "./AgentGate"

const STATUS = {
  ready: { label: "Online", dot: "bg-emerald-500" },
  creating: { label: "Waking up", dot: "bg-amber-400 animate-pulse" },
  failed: { label: "Needs attention", dot: "bg-destructive" },
} as const

export default function AgentOverview({ state }: { state: AgentState }) {
  const { setState } = useAgent()
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState("")
  const agent = state.agent
  const telegram = useQuery({
    queryKey: ["agent", "telegram"],
    queryFn: AgentService.telegram,
    enabled: agent?.status === "ready",
    staleTime: 30_000,
  })
  const tg = telegram.data
  const connected = !!tg?.attached && tg.ready && tg.approvedUserIds.length > 0
  const botUrl = publicBotUrl(tg?.botUsername ?? null)
  const firstName = state.draft.profile.name.split(" ")[0]
  const status = STATUS[agent?.status ?? "creating"]
  const context = state.draft.profile.whatYouDo.trim()

  async function apply() {
    setApplying(true)
    setError("")
    try {
      setState(await AgentService.sync(state.revision))
    } catch (e) {
      setError(agentError(e))
    } finally {
      setApplying(false)
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-8 px-4 py-6 sm:px-8 sm:py-10">
      <AgentPageHeader
        title={firstName ? `${firstName}’s agent` : "Your agent"}
      >
        <span className="inline-flex items-center gap-2 rounded-full border bg-card px-3 py-1 text-sm">
          <span className={cn("size-2 rounded-full", status.dot)} />
          {status.label}
        </span>
      </AgentPageHeader>

      {(state.contextPending || state.hostError || error) && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/40 bg-amber-500/5 p-4 text-sm"
        >
          <span>
            {error ||
              (state.hostError
                ? `Your agent’s host reported: ${agentError({ message: state.hostError })}`
                : "You have changes your agent hasn’t received yet.")}
          </span>
          <Button size="sm" disabled={applying} onClick={apply}>
            {applying && (
              <Loader2
                className="mr-2 size-4 animate-spin"
                aria-hidden="true"
              />
            )}
            Apply changes
          </Button>
        </div>
      )}

      <section className="grid gap-4 md:grid-cols-2">
        <Tile
          icon={Send}
          title="Telegram"
          className="md:col-span-2"
          meta={
            telegram.isLoading
              ? "Checking…"
              : connected
                ? `Connected${tg?.botUsername ? ` as @${tg.botUsername}` : ""}`
                : "Not connected"
          }
        >
          {connected ? (
            <div className="flex flex-wrap items-center gap-3">
              <p className="mr-auto text-sm text-muted-foreground">
                Message your agent anytime. It checks with you here before doing
                anything that matters.
              </p>
              {botUrl && (
                <Button asChild>
                  <a href={botUrl} target="_blank" rel="noreferrer noopener">
                    Open Telegram
                    <ExternalLink className="ml-2 size-4" aria-hidden="true" />
                  </a>
                </Button>
              )}
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-3">
              <p className="mr-auto text-sm text-muted-foreground">
                Connect Telegram to talk to your agent from your phone.
              </p>
              <Button asChild>
                <Link href="/portal/agent/connections">
                  Connect Telegram
                  <ArrowRight className="ml-2 size-4" aria-hidden="true" />
                </Link>
              </Button>
            </div>
          )}
        </Tile>

        <Tile
          icon={NotebookPen}
          title="What it knows about you"
          meta={`${wordCount(context).toLocaleString()} words`}
          href="/portal/agent/context"
          cta="Edit"
        >
          <p className="line-clamp-4 whitespace-pre-line text-sm text-muted-foreground">
            {context}
          </p>
        </Tile>

        <div className="grid gap-4">
          <Tile
            icon={ShieldCheck}
            title="Privacy"
            meta={
              state.consent.research
                ? `Research on · Training ${state.consent.training ? "on" : "off"}`
                : "Research withdrawn"
            }
            href="/portal/agent/privacy"
            cta="Manage"
          />
          <Tile
            icon={Monitor}
            title="Hermes Desktop"
            meta="Optional desktop app"
            href="/portal/agent/connections"
            cta="Set up"
          />
        </div>
      </section>
    </div>
  )
}

function Tile({
  icon: Icon,
  title,
  meta,
  href,
  cta,
  className,
  children,
}: {
  icon: typeof Send
  title: string
  meta?: string
  href?: string
  cta?: string
  className?: string
  children?: React.ReactNode
}) {
  return (
    <div className={cn("rounded-2xl border bg-card p-5 sm:p-6", className)}>
      <div className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="size-4" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold">{title}</h2>
          {meta && <p className="text-sm text-muted-foreground">{meta}</p>}
        </div>
        {href && cta && (
          <Button asChild variant="ghost" size="sm">
            <Link href={href}>{cta}</Link>
          </Button>
        )}
      </div>
      {children && <div className="mt-4">{children}</div>}
    </div>
  )
}
