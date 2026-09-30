"use client"

import { useEffect, useRef, useState } from "react"
import { Loader2 } from "lucide-react"
import QRCode from "react-qr-code"
import { Button } from "@/components/ui/button"
import {
  AgentService,
  agentError,
  type TelegramSetupState,
} from "@/lib/agentService"

function botFatherLink(value?: string): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    const nativeBotCreation = /^\/newbot\/[A-Za-z0-9_]+\/[A-Za-z0-9_]+$/.test(
      url.pathname,
    )
    const pairingBot =
      /^\/[A-Za-z0-9_]{5,32}$/.test(url.pathname) &&
      /^pair_[A-Za-z0-9_-]+$/.test(url.searchParams.get("start") || "")
    if (
      url.protocol === "https:" &&
      url.hostname === "t.me" &&
      (nativeBotCreation || pairingBot) &&
      !url.username &&
      !url.password &&
      !url.port &&
      !url.hash
    )
      return value
  } catch {
    /* Never render invalid upstream links. */
  }
  return null
}

const spinner = (
  <Loader2 aria-hidden="true" className="h-4 w-4 motion-safe:animate-spin" />
)

export default function TelegramQuickSetup({
  initialId,
  onApplied,
  onManual,
  disabled = false,
}: {
  initialId: string | null
  onApplied: () => void
  onManual: () => void
  disabled?: boolean
}) {
  const [id, setId] = useState(initialId)
  const [state, setState] = useState<TelegramSetupState | null>(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState("")
  const [confirmedOwner, setConfirmedOwner] = useState("")
  const [now, setNow] = useState(Date.now())
  const [generation, setGeneration] = useState(0)
  const [paused, setPaused] = useState(false)
  const alive = useRef(true)
  const revision = useRef(0)
  const pendingRead = useRef<Promise<TelegramSetupState> | null>(null)
  const applied = useRef(onApplied)
  applied.current = onApplied
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      revision.current++
    }
  }, [])
  useEffect(() => {
    if (initialId) setId(initialId)
  }, [initialId])
  const expired =
    !!state && Date.parse(state.expires_at) <= now && state.status !== "applied"
  const link = botFatherLink(state?.deep_link)
  const qr = botFatherLink(state?.qr_payload)

  useEffect(() => {
    if (!id || busy || disabled || error) return
    let active = true
    let timer: number | undefined
    const version = revision.current
    const deadline = Date.now() + 5 * 60_000
    async function refresh() {
      try {
        if (pendingRead.current) await pendingRead.current.catch(() => {})
        if (!active || version !== revision.current) return
        const request = AgentService.telegramSetup(id!)
        pendingRead.current = request
        const next = await request.finally(() => {
          if (pendingRead.current === request) pendingRead.current = null
        })
        if (!active || version !== revision.current) return
        setState((previous) => ({
          ...next,
          deep_link: next.deep_link || previous?.deep_link,
          qr_payload: next.qr_payload || previous?.qr_payload,
        }))
        setNow(Date.now())
        setError("")
        if (next.status === "applied") {
          applied.current()
          return
        }
        if (
          next.status === "waiting" &&
          Date.parse(next.expires_at) > Date.now()
        ) {
          if (Date.now() < deadline) timer = window.setTimeout(refresh, 3000)
          else setPaused(true)
        }
      } catch (e) {
        if (active && version === revision.current) {
          setError(agentError(e))
          setPaused(true)
        }
      }
    }
    setPaused(false)
    void refresh()
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [id, generation, busy, disabled, error])

  useEffect(() => {
    if (!state || state.status === "applied") return
    const remaining = Date.parse(state.expires_at) - Date.now()
    if (!Number.isFinite(remaining)) return
    const timer = setTimeout(
      () => setNow(Date.now()),
      Math.max(0, remaining) + 50,
    )
    return () => clearTimeout(timer)
  }, [state])

  async function act(action: "start" | "cancel" | "approve") {
    if (busy || disabled) return
    if (
      action === "approve" &&
      (!id ||
        !state?.owner_user_id ||
        !/^\d+$/.test(state.owner_user_id) ||
        confirmedOwner !== state.owner_user_id ||
        expired)
    )
      return
    revision.current++
    setBusy(action)
    setError("")
    try {
      if (action === "start") {
        const result = await AgentService.startTelegramSetup()
        if (!alive.current) return
        setState({
          status: "waiting",
          expires_at: result.expires_at,
          deep_link: result.deep_link,
          qr_payload: result.qr_payload,
        })
        setId(result.pairing_id)
        setNow(Date.now())
      } else if (action === "cancel") {
        await AgentService.cancelTelegramSetup(id!)
        if (!alive.current) return
        setId(null)
        setState(null)
      } else {
        await AgentService.applyTelegramSetup(id!, state!.owner_user_id!)
        if (!alive.current) return
        applied.current()
      }
      if (alive.current) setConfirmedOwner("")
    } catch (e) {
      if (alive.current) {
        setError(agentError(e))
        setPaused(true)
      }
    } finally {
      if (alive.current) setBusy("")
    }
  }

  return (
    <div className="space-y-4">
      {error && (
        <p role="alert" className="break-words text-sm text-destructive">
          {error}
        </p>
      )}
      {!id && (
        <Button disabled={!!busy || disabled} onClick={() => void act("start")}>
          {busy === "start" && spinner}
          {busy === "start" ? "Creating setup…" : "Connect Telegram"}
        </Button>
      )}
      {!id && !busy && (
        <button
          type="button"
          disabled={disabled}
          className="block text-sm text-muted-foreground underline underline-offset-4"
          onClick={onManual}
        >
          I already have a bot token
        </button>
      )}
      {id && !state && !error && (
        <p role="status" className="flex items-center gap-2 text-sm">
          {spinner}Loading your saved setup…
        </p>
      )}
      {state?.status === "waiting" && !expired && (
        <>
          <h3 className="text-lg font-semibold">Create your bot in Telegram</h3>
          <p className="text-sm text-muted-foreground">
            <span className="md:hidden">
              Tap below to open Telegram, then tap Create. Come back here when
              it’s done.
            </span>
            <span className="hidden md:inline">
              Scan the code with your phone, or open Telegram on this computer,
              then tap Create.
            </span>
          </p>
          <div className="flex flex-wrap items-center gap-5">
            {qr && (
              // Scanning needs a second device; on phones the link opens
              // Telegram directly, so the code only shows on larger screens.
              <div className="hidden rounded-xl bg-white p-3 md:block">
                <QRCode
                  value={qr}
                  size={144}
                  title="Private Telegram bot setup"
                />
              </div>
            )}
            <div className="w-full space-y-3 md:w-auto">
              {link ? (
                <a
                  href={link}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex min-h-11 w-full items-center justify-center rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground md:w-auto"
                >
                  Open Telegram
                </a>
              ) : (
                <p className="text-sm">
                  No valid setup link. Cancel this setup to start again.
                </p>
              )}
              {!error && !paused && !busy && (
                <p role="status" className="flex items-center gap-2 text-sm">
                  {spinner}Waiting for you to create the bot…
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                Keep this link private. Expires{" "}
                {new Date(state.expires_at).toLocaleTimeString([], {
                  hour: "numeric",
                  minute: "2-digit",
                })}
                .
              </p>
            </div>
          </div>
        </>
      )}
      {expired && (
        <div className="space-y-3">
          <p role="status" className="text-sm">
            This setup link expired.
          </p>
          <Button
            disabled={!!busy || disabled}
            onClick={() => void act("start")}
          >
            {busy === "start" && spinner}
            {busy === "start" ? "Creating setup…" : "Create new link"}
          </Button>
        </div>
      )}
      {state?.status === "ready" && !expired && (
        <>
          <h3 className="text-lg font-semibold">
            Approve your Telegram account
          </h3>
          {state.bot_username && (
            <p className="break-all text-sm">Bot: @{state.bot_username}</p>
          )}
          <p className="break-all text-sm">
            Telegram user ID:{" "}
            <strong>{state.owner_user_id || "Unavailable"}</strong>
          </p>
          <label className="flex items-start gap-3 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              disabled={
                !!busy ||
                disabled ||
                !state.owner_user_id ||
                !/^\d+$/.test(state.owner_user_id)
              }
              checked={
                !!state.owner_user_id && confirmedOwner === state.owner_user_id
              }
              onChange={(e) =>
                setConfirmedOwner(
                  e.target.checked ? state.owner_user_id || "" : "",
                )
              }
            />
            I verified this numeric ID is mine and created this bot. Allow this
            account to use my agent.
          </label>
          <Button
            disabled={
              !!busy ||
              disabled ||
              !state.owner_user_id ||
              !/^\d+$/.test(state.owner_user_id) ||
              confirmedOwner !== state.owner_user_id
            }
            onClick={() => void act("approve")}
          >
            {busy === "approve" && spinner}
            {busy === "approve" ? "Connecting your bot…" : "Approve & connect"}
          </Button>
          {busy === "approve" && (
            <p role="status" className="text-sm text-muted-foreground">
              Your agent restarts its Telegram connection. This can take up to a
              couple of minutes; keep this page open.
            </p>
          )}
        </>
      )}
      {paused && !error && !expired && (
        <p role="status" className="text-sm text-muted-foreground">
          Automatic checks paused. Check again when you’re ready.
        </p>
      )}
      {id && (
        <div className="flex flex-wrap gap-2">
          {(error || paused) && !expired && (
            <Button
              variant="outline"
              disabled={!!busy || disabled}
              onClick={() => {
                setError("")
                setGeneration((value) => value + 1)
              }}
            >
              Check again
            </Button>
          )}
          <Button
            variant="ghost"
            disabled={!!busy || disabled}
            onClick={() => void act("cancel")}
          >
            {busy === "cancel" && spinner}
            {busy === "cancel" ? "Cancelling…" : "Cancel setup"}
          </Button>
        </div>
      )}
    </div>
  )
}
