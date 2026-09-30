"use client"

import AgentGate, { AgentPageHeader } from "../AgentGate"
import DesktopPanel from "../DesktopPanel"
import TelegramPanel from "../TelegramPanel"

export default function AgentConnectionsPage() {
  return (
    <AgentGate>
      {(state) => (
        <div className="mx-auto max-w-3xl space-y-8 px-4 py-6 sm:px-8 sm:py-10">
          <AgentPageHeader
            title="Connections"
            lead="Where you talk to your agent."
          />
          <section className="rounded-2xl border bg-card p-5 sm:p-6">
            <h2 className="mb-4 text-lg font-semibold">Telegram</h2>
            {state.agent?.status === "ready" ? (
              <TelegramPanel
                disabled={false}
                pairingId={state.telegramPairingId}
              />
            ) : (
              <p className="text-sm text-muted-foreground">
                Available once your agent is online.
              </p>
            )}
          </section>
          <section className="rounded-2xl border bg-card px-5 sm:px-6">
            <DesktopPanel />
          </section>
        </div>
      )}
    </AgentGate>
  )
}
