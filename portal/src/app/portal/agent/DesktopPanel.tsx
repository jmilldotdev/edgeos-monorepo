"use client"

import { Check, Loader2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { AgentService, type DesktopAttempt } from "@/lib/agentService"

const pending = (attempt: DesktopAttempt | null) =>
  attempt?.status === "pending" || attempt?.status === "opened"

const terminalMessage = {
  expired: "This Desktop link has expired.",
  cancelled: "The Desktop connection was cancelled.",
  failed: "Desktop could not complete the connection.",
  incompatible: "Update Hermes Desktop to connect, then try again.",
}

export default function DesktopPanel() {
  const [open, setOpen] = useState(false)
  const [attempt, setAttempt] = useState<DesktopAttempt | null>(null)
  const [link, setLink] = useState<{ id: string; url: string } | null>(null)
  const [creating, setCreating] = useState(false)
  const [checking, setChecking] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [expired, setExpired] = useState(false)
  const [error, setError] = useState<"check" | "create" | "link" | null>(null)
  const [retry, setRetry] = useState(0)
  const mounted = useRef(false)
  const mutation = useRef(false)
  const generation = useRef(0)
  const readRequest = useRef<Promise<{
    attempt: DesktopAttempt | null
  }> | null>(null)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      generation.current += 1
    }
  }, [])

  useEffect(() => {
    if (!pending(attempt)) {
      setExpired(false)
      return
    }
    const remaining = Date.parse(attempt!.expiresAt) - Date.now()
    if (!Number.isFinite(remaining) || remaining <= 0) {
      setExpired(true)
      return
    }
    setExpired(false)
    const timer = setTimeout(() => setExpired(true), remaining)
    return () => clearTimeout(timer)
  }, [attempt])

  useEffect(() => {
    if (!open || creating || error || expired) {
      setChecking(false)
      return
    }
    let cancelled = false
    let timer: number | undefined
    const currentGeneration = generation.current
    const active = () => !cancelled && currentGeneration === generation.current

    async function refresh(initial: boolean) {
      if (initial) setChecking(true)
      try {
        // Share an outstanding read across StrictMode effect replays.
        const request = readRequest.current ?? AgentService.desktop()
        readRequest.current = request
        let result: Awaited<typeof request>
        try {
          result = await request
        } finally {
          if (readRequest.current === request) readRequest.current = null
        }
        if (!active()) return
        setAttempt(result.attempt)
        setLoaded(true)
        setChecking(false)
        setError(null)
        const remaining = result.attempt
          ? Date.parse(result.attempt.expiresAt) - Date.now()
          : 0
        if (
          pending(result.attempt) &&
          link?.id === result.attempt?.id &&
          remaining > 0
        ) {
          timer = window.setTimeout(
            () => {
              if (Date.parse(result.attempt!.expiresAt) > Date.now())
                void refresh(false)
            },
            Math.min(3000, remaining),
          )
        }
      } catch {
        if (!active()) return
        setChecking(false)
        setError("check")
      }
    }

    void refresh(true)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [open, creating, link, retry, error, expired])

  async function connect() {
    if (mutation.current || checking) return
    mutation.current = true
    const currentGeneration = ++generation.current
    setCreating(true)
    setError(null)
    try {
      // Finish any older read before creating its replacement, so it cannot
      // be reused as the first status check for the new handoff.
      await readRequest.current?.catch(() => undefined)
      if (!mounted.current || generation.current !== currentGeneration) return
      const result = await AgentService.connectDesktop()
      if (!mounted.current || generation.current !== currentGeneration) return
      setAttempt(result.attempt)
      setLoaded(true)
      setLink(null)
      try {
        if (new URL(result.deepLink).protocol !== "hermes:") throw new Error()
        setLink({ id: result.attempt.id, url: result.deepLink })
      } catch {
        setError("link")
      }
    } catch {
      if (mounted.current && generation.current === currentGeneration)
        setError("create")
    } finally {
      mutation.current = false
      if (mounted.current && generation.current === currentGeneration)
        setCreating(false)
    }
  }

  const isExpired =
    pending(attempt) &&
    (expired ||
      !Number.isFinite(Date.parse(attempt!.expiresAt)) ||
      Date.parse(attempt!.expiresAt) <= Date.now())
  const handoff =
    pending(attempt) && !isExpired && link && link.id === attempt?.id
      ? link.url
      : null
  const connected = attempt?.status === "connected"
  const waiting = Boolean(handoff) && !error && !creating
  const status = connected
    ? "Desktop connected"
    : isExpired
      ? terminalMessage.expired
      : attempt && attempt.status in terminalMessage
        ? terminalMessage[attempt.status as keyof typeof terminalMessage]
        : pending(attempt) && !handoff
          ? "Create a new link to continue on this browser."
          : null
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="cursor-pointer py-4 text-sm font-medium">
        Hermes Desktop{" "}
        <span className="font-normal text-muted-foreground">
          · optional, for longer sessions on your computer
        </span>
      </summary>
      <div className="space-y-3 pb-2 pt-2">
        <div role="status" aria-live="polite" className="text-sm">
          {creating ? (
            <span className="flex items-center gap-2">
              <Loader2
                aria-hidden="true"
                className="h-4 w-4 animate-spin motion-reduce:animate-none"
              />
              Creating Desktop link…
            </span>
          ) : waiting ? (
            <span className="flex items-center gap-2">
              <Loader2
                aria-hidden="true"
                className="h-4 w-4 animate-spin motion-reduce:animate-none"
              />
              Waiting for Desktop…
            </span>
          ) : status ? (
            <span className="flex items-center gap-2">
              {connected && <Check aria-hidden="true" className="h-4 w-4" />}
              {status}
            </span>
          ) : checking || (!loaded && !error) ? (
            <span className="flex items-center gap-2">
              <Loader2
                aria-hidden="true"
                className="h-4 w-4 animate-spin motion-reduce:animate-none"
              />
              Checking Desktop…
            </span>
          ) : (
            <p className="text-muted-foreground">
              Connect with the Hermes Desktop app.
            </p>
          )}
        </div>
        {error && !(error === "check" && isExpired) && (
          <p role="alert" className="text-sm text-destructive">
            {error === "check"
              ? "Could not check Desktop. Try again to resume checking."
              : error === "link"
                ? "This Desktop link could not be opened. Create a new link."
                : "Could not create a Desktop link. Please try again."}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3">
          {handoff && !creating && (
            <a
              href={handoff}
              className="inline-flex min-h-11 items-center rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Open Hermes Desktop
            </a>
          )}
          {error === "check" && !isExpired ? (
            <Button
              variant="outline"
              disabled={checking}
              onClick={() => {
                setError(null)
                setRetry((value) => value + 1)
              }}
            >
              {checking ? "Checking…" : "Retry status check"}
            </Button>
          ) : (
            !connected &&
            !handoff && (
              <Button
                variant="outline"
                disabled={creating || checking || (!loaded && !error)}
                onClick={connect}
              >
                {creating
                  ? "Creating link…"
                  : attempt
                    ? "Create new Desktop link"
                    : error
                      ? "Try again"
                      : "Connect Desktop"}
              </Button>
            )
          )}
        </div>
        {handoff && !creating && (
          <p className="text-xs text-muted-foreground">
            Open the link and finish connecting in Hermes Desktop. Keep this
            single-use link private.
          </p>
        )}
      </div>
    </details>
  )
}
