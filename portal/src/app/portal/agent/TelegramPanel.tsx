"use client"

import { Check, Loader2 } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import QRCode from "react-qr-code"
import { Button } from "@/components/ui/button"
import {
  AgentService,
  agentError,
  publicBotUrl,
  type TelegramState,
} from "@/lib/agentService"
import TelegramQuickSetup from "./TelegramQuickSetup"

const spinner = (
  <Loader2 aria-hidden="true" className="h-4 w-4 motion-safe:animate-spin" />
)
const linkStyle =
  "inline-flex min-h-11 items-center rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"

export default function TelegramPanel({
  disabled,
  pairingId,
}: {
  disabled: boolean
  pairingId: string | null
}) {
  const [state, setState] = useState<TelegramState | null>(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState("")
  const [token, setToken] = useState("")
  const [approval, setApproval] = useState("")
  const [revoke, setRevoke] = useState("")
  const [managedFinished, setManagedFinished] = useState(false)
  const [manual, setManual] = useState(false)
  const [generation, setGeneration] = useState(0)
  const [checking, setChecking] = useState(false)
  const [paused, setPaused] = useState(false)
  const alive = useRef(true)
  const revision = useRef(0)
  const inFlight = useRef<Promise<TelegramState> | null>(null)
  const connected =
    !!state?.attached && state.ready && state.approvedUserIds.length > 0
  const managed =
    !connected &&
    !managedFinished &&
    !manual &&
    (!!pairingId || !state?.attached)
  const url = publicBotUrl(state?.botUsername || null)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      revision.current++
    }
  }, [])
  const load = useCallback(async () => {
    while (inFlight.current) await inFlight.current.catch(() => {})
    const request = AgentService.telegram()
    inFlight.current = request
    try {
      return await request
    } finally {
      if (inFlight.current === request) inFlight.current = null
    }
  }, [])

  useEffect(() => {
    if (disabled || busy || error) return
    let active = true
    let timer: number | undefined
    const version = revision.current
    const deadline = Date.now() + 5 * 60_000
    async function refresh() {
      setChecking(true)
      try {
        const next = await load()
        if (!active || version !== revision.current) return
        setState(next)
        const complete =
          next.attached && next.ready && next.approvedUserIds.length > 0
        const waiting =
          next.supported &&
          next.attached &&
          !complete &&
          (next.pending.length === 0 || !next.ready)
        if (waiting && Date.now() < deadline)
          timer = window.setTimeout(refresh, 3000)
        else {
          setChecking(false)
          if (waiting) setPaused(true)
        }
      } catch (e) {
        if (active && version === revision.current) {
          setError(agentError(e))
          setChecking(false)
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
  }, [disabled, busy, error, generation, load])

  const refresh = useCallback(() => {
    revision.current++
    setError("")
    setGeneration((value) => value + 1)
  }, [])
  async function run(label: string, action: () => Promise<unknown>) {
    if (busy || disabled) return
    revision.current++
    setBusy(label)
    setChecking(false)
    setError("")
    try {
      // Finish any old read before mutating so it cannot overwrite the result.
      if (inFlight.current) await inFlight.current.catch(() => {})
      await action()
      if (!alive.current) return
      setApproval("")
      setRevoke("")
      if (label === "attach") {
        setManagedFinished(true)
        setManual(false)
      }
      const next = await load()
      if (alive.current) setState(next)
    } catch (e) {
      if (alive.current) setError(agentError(e))
    } finally {
      if (alive.current) {
        setBusy("")
        setGeneration((value) => value + 1)
      }
    }
  }

  function tokenForm() {
    return (
      <div className="space-y-3">
        <p className="text-sm text-muted-foreground">
          Create a bot with{" "}
          <a
            className="underline"
            href="https://t.me/BotFather"
            target="_blank"
            rel="noreferrer noopener"
          >
            @BotFather
          </a>{" "}
          using /newbot, then paste its token here.
        </p>
        <label className="block text-sm font-medium">
          Private bot token
          <input
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={token}
            onChange={(event) => setToken(event.target.value)}
            className="mt-2 block w-full rounded-lg border bg-background px-3 py-2 text-sm"
            placeholder="Paste your BotFather token"
          />
        </label>
        <p className="text-xs text-muted-foreground">
          Sent only to your authenticated backend. Never saved as a browser
          draft or included in a QR.
        </p>
        <Button
          disabled={!token.trim() || !!busy || disabled}
          onClick={() => {
            const secret = token.trim()
            setToken("")
            void run("attach", () =>
              AgentService.telegramAction({ action: "attach", token: secret }),
            )
          }}
        >
          {busy === "attach" && spinner}
          {busy === "attach"
            ? "Attaching bot…"
            : state?.attached
              ? "Replace token & attach"
              : "Attach bot"}
        </Button>
      </div>
    )
  }
  function pendingRequests() {
    return (
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Approve only a request you initiated. A display name alone is not
          proof of identity.
        </p>
        {state?.pending.map((pair) => {
          const key = `${pair.code}:${pair.userId}`
          const expired = pair.expiresAt
            ? Date.parse(pair.expiresAt) <= Date.now()
            : pair.ageMinutes !== null && pair.ageMinutes >= 60
          return (
            <div key={key} className="space-y-3 rounded-xl border p-4 text-sm">
              <p className="break-words font-medium">
                {pair.userName || "Telegram account"}
              </p>
              <p className="break-all">
                Telegram user ID: <strong>{pair.userId}</strong>
              </p>
              <p className="text-xs text-muted-foreground">
                {expired
                  ? "This request expired. Send a new message in Telegram."
                  : pair.expiresAt
                    ? `Expires ${new Date(pair.expiresAt).toLocaleTimeString()}`
                    : "Requests expire after one hour."}
              </p>
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={approval === key}
                  disabled={expired || !!busy || disabled}
                  onChange={(event) =>
                    setApproval(event.target.checked ? key : "")
                  }
                />
                I verified this numeric ID is mine. Allow this account to use my
                agent.
              </label>
              <Button
                disabled={
                  expired ||
                  !/^\d+$/.test(pair.userId) ||
                  approval !== key ||
                  !!busy ||
                  disabled
                }
                onClick={() => {
                  if (
                    pair.expiresAt &&
                    Date.parse(pair.expiresAt) <= Date.now()
                  ) {
                    refresh()
                    return
                  }
                  void run("approve", () =>
                    AgentService.telegramAction({
                      action: "approve",
                      code: pair.code,
                      userId: pair.userId,
                      confirmed: true,
                    }),
                  )
                }}
              >
                {busy === "approve" && spinner}
                {busy === "approve"
                  ? "Approving account…"
                  : "Approve this account"}
              </Button>
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <section aria-label="Telegram connection">
      {error && (
        <div className="space-y-3">
          <p role="alert" className="break-words text-sm text-destructive">
            {error}
          </p>
          <Button
            variant="outline"
            disabled={!!busy || disabled}
            onClick={refresh}
          >
            Check again
          </Button>
        </div>
      )}
      {!state && !error && (
        <p role="status" className="flex items-center gap-2 text-sm">
          {!disabled && spinner}
          {disabled
            ? "Start your agent to connect Telegram."
            : "Checking Telegram…"}
        </p>
      )}
      {state && !state.supported && (
        <p className="text-sm text-muted-foreground">
          This runtime does not support Telegram.
        </p>
      )}
      {state?.supported && (
        <fieldset disabled={disabled || !!busy} className="min-w-0 space-y-5">
          {connected ? (
            <div className="space-y-4">
              <p
                role="status"
                className="flex items-center gap-2 break-all text-sm font-medium"
              >
                <Check
                  className="size-4 text-emerald-600 dark:text-emerald-400"
                  aria-hidden="true"
                />
                Connected{state.botUsername ? ` as @${state.botUsername}` : ""}
              </p>
              {url ? (
                <a
                  className={linkStyle}
                  href={url}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  Open Telegram
                </a>
              ) : (
                <p className="text-sm">
                  Open your bot in Telegram. Its public username is unavailable
                  here.
                </p>
              )}
              {url && (
                <details className="text-sm text-muted-foreground">
                  <summary className="w-fit cursor-pointer">
                    Show QR code
                  </summary>
                  <div className="mt-3 w-fit rounded-xl bg-white p-3">
                    <QRCode
                      value={url}
                      size={128}
                      title="Open your Telegram bot"
                    />
                  </div>
                </details>
              )}
            </div>
          ) : managed ? (
            <TelegramQuickSetup
              initialId={pairingId}
              disabled={disabled}
              onManual={() => setManual(true)}
              onApplied={() => {
                setManagedFinished(true)
                refresh()
              }}
            />
          ) : manual ? (
            <div className="space-y-4">
              <h3 className="font-semibold">Use your own bot</h3>
              {tokenForm()}
              <Button variant="ghost" onClick={() => setManual(false)}>
                Back
              </Button>
            </div>
          ) : state.attached ? (
            <div className="space-y-4">
              {!state.ready ? (
                <>
                  <h3 className="font-semibold">Starting Telegram</h3>
                  <p
                    role="status"
                    className="flex items-center gap-2 text-sm text-muted-foreground"
                  >
                    {checking && !error && spinner}
                    {checking && !error
                      ? "Waiting for your bot to come online…"
                      : "Your bot is attached, but isn’t ready yet."}
                  </p>
                </>
              ) : state.pending.length ? (
                <>
                  <h3 className="font-semibold">
                    Approve your Telegram account
                  </h3>
                  {pendingRequests()}
                </>
              ) : (
                <>
                  <h3 className="font-semibold">Send your bot a message</h3>
                  <p className="text-sm text-muted-foreground">
                    Open your bot, tap Start and send “Hello”. Then approve your
                    account here.
                  </p>
                  {url ? (
                    <a
                      className={linkStyle}
                      href={url}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      Open Telegram
                    </a>
                  ) : (
                    <p className="text-sm">
                      The bot’s public username isn’t available yet.
                    </p>
                  )}
                  <p
                    role="status"
                    className="flex items-center gap-2 text-sm text-muted-foreground"
                  >
                    {checking && !error && spinner}
                    {checking && !error
                      ? "Waiting for your message…"
                      : "No pending request yet."}
                  </p>
                </>
              )}
              {paused && !error && (
                <p role="status" className="text-sm text-muted-foreground">
                  Automatic checks paused.
                </p>
              )}
              {(!checking || paused) && !error && (
                <Button variant="outline" onClick={refresh}>
                  Check again
                </Button>
              )}
            </div>
          ) : (
            <Button
              onClick={() => {
                setManagedFinished(false)
                setManual(false)
              }}
            >
              Connect Telegram
            </Button>
          )}
          {state.attached && !managed && (
            <details className="border-t pt-4 text-sm">
              <summary className="w-fit cursor-pointer text-muted-foreground">
                Manage Telegram
              </summary>
              <div className="mt-4 space-y-5">
                <div>
                  <h3 className="font-medium">Approved accounts</h3>
                  {!state.approvedUserIds.length && (
                    <p className="mt-2 text-muted-foreground">
                      No accounts approved.
                    </p>
                  )}
                  {state.approvedUserIds.map((id) => (
                    <div
                      key={id}
                      className="mt-3 space-y-3 rounded-xl border p-3"
                    >
                      <p className="break-all">
                        Telegram user ID: <strong>{id}</strong>
                      </p>
                      <label className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={revoke === id}
                          onChange={(event) =>
                            setRevoke(event.target.checked ? id : "")
                          }
                        />
                        Remove this account’s access
                      </label>
                      <Button
                        variant="outline"
                        disabled={revoke !== id || !!busy}
                        onClick={() =>
                          void run("revoke", () =>
                            AgentService.telegramAction({
                              action: "revoke",
                              userId: id,
                              confirmed: true,
                            }),
                          )
                        }
                      >
                        {busy === "revoke" && spinner}
                        {busy === "revoke"
                          ? "Revoking access…"
                          : "Revoke access"}
                      </Button>
                    </div>
                  ))}
                </div>
                {connected && state.pending.length > 0 && (
                  <div>
                    <h3 className="mb-3 font-medium">Pending accounts</h3>
                    {pendingRequests()}
                  </div>
                )}
                <Button variant="outline" onClick={refresh} disabled={checking}>
                  {checking && spinner}
                  {checking ? "Checking…" : "Refresh accounts"}
                </Button>
                <div className="space-y-3 border-t pt-4">
                  <h3 className="font-medium">Replace bot token</h3>
                  {tokenForm()}
                  <p className="text-xs text-muted-foreground">
                    Revoking account access does not delete the bot. To
                    invalidate its token, use /revoke in BotFather.
                  </p>
                </div>
              </div>
            </details>
          )}
        </fieldset>
      )}
    </section>
  )
}
