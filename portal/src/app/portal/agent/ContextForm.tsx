"use client"

import { Check, ChevronDown, Copy } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  type AgentDraft,
  extraContext,
  withExtraContext,
  wordCount,
} from "@/lib/agentService"

function contextPrompt(eventName: string) {
  return `I'm going to ${eventName}, an Edge City popup village for people working at the frontier of tech, science and culture. I'm setting up a personal AI agent that will represent me there: it looks for collaborators, suggests introductions and surfaces events, and always asks me before it acts.

Using everything you know about me, write a profile for that agent in the first person, under these headings:

1. What I'm working on right now
2. What I'm deeply curious about
3. What I can help other people with
4. The kinds of people I'd like to meet, and why
5. What I hope to leave with
6. How I like to be approached (tone, timing, things to avoid)
7. What I do for fun

Be specific and concrete: "looking for two people to test a local-first notes prototype" beats "interested in productivity". Only include what you actually know about me; say less rather than invent. Leave out anything private or sensitive, like health, money, relationships and passwords.`
}

/**
 * The participant's self-description. Leads with the fastest route to rich
 * context: ask an AI that already knows them, paste its answer, edit.
 */
export default function ContextForm({
  draft,
  onChange,
  eventName,
  guided = true,
}: {
  draft: AgentDraft
  onChange: (draft: AgentDraft) => void
  eventName: string
  /** Show the ask-your-AI walkthrough above the text box. */
  guided?: boolean
}) {
  const [copied, setCopied] = useState<"idle" | "copied" | "failed">("idle")
  const [showPrompt, setShowPrompt] = useState(false)
  const prompt = contextPrompt(eventName)
  const words = wordCount(draft.profile.whatYouDo)
  const profile = (field: keyof AgentDraft["profile"], value: string) =>
    onChange({ ...draft, profile: { ...draft.profile, [field]: value } })

  async function copy() {
    try {
      await navigator.clipboard.writeText(prompt)
      setCopied("copied")
    } catch {
      setCopied("failed")
      setShowPrompt(true)
    }
  }

  return (
    <div className="space-y-8">
      {guided && (
        <ol className="grid gap-3 sm:grid-cols-3">
          <li className="rounded-xl border bg-card p-4">
            <p className="text-xs font-semibold text-primary">Step 1</p>
            <p className="mt-1 font-medium">Copy our prompt</p>
            <Button
              type="button"
              size="sm"
              variant={copied === "copied" ? "outline" : "default"}
              className="mt-3 w-full"
              onClick={copy}
            >
              {copied === "copied" ? (
                <Check className="mr-2 size-4" aria-hidden="true" />
              ) : (
                <Copy className="mr-2 size-4" aria-hidden="true" />
              )}
              {copied === "copied" ? "Copied" : "Copy prompt"}
            </Button>
          </li>
          <li className="rounded-xl border bg-card p-4">
            <p className="text-xs font-semibold text-primary">Step 2</p>
            <p className="mt-1 font-medium">Paste it into your AI</p>
            <p className="mt-1 text-sm text-muted-foreground">
              ChatGPT, Claude, Gemini… whichever knows you best.
            </p>
          </li>
          <li className="rounded-xl border bg-card p-4">
            <p className="text-xs font-semibold text-primary">Step 3</p>
            <p className="mt-1 font-medium">Paste its answer below</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Then edit anything that isn’t quite you.
            </p>
          </li>
        </ol>
      )}
      {guided && (
        <div className="-mt-5">
          <button
            type="button"
            aria-expanded={showPrompt}
            onClick={() => setShowPrompt(!showPrompt)}
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ChevronDown
              className={`size-4 transition-transform ${showPrompt ? "rotate-180" : ""}`}
              aria-hidden="true"
            />
            {showPrompt ? "Hide the prompt" : "Read the prompt"}
          </button>
          {copied === "failed" && (
            <p role="status" className="mt-2 text-sm text-destructive">
              Couldn’t reach your clipboard. Select the prompt below and copy
              it.
            </p>
          )}
          {showPrompt && (
            <Textarea
              readOnly
              value={prompt}
              rows={10}
              aria-label="Prompt for your AI"
              onFocus={(event) => event.currentTarget.select()}
              className="mt-2 bg-muted/40 font-mono text-xs leading-relaxed"
            />
          )}
        </div>
      )}

      <label className="block">
        <span className="flex items-baseline justify-between gap-3">
          <span className="font-medium">
            {guided ? "Your AI’s answer" : "What your agent knows about you"}
          </span>
          <span className="text-xs tabular-nums text-muted-foreground">
            {words} {words === 1 ? "word" : "words"}
          </span>
        </span>
        <Textarea
          value={draft.profile.whatYouDo}
          onChange={(event) => profile("whatYouDo", event.target.value)}
          placeholder={
            guided
              ? "Paste here — or write it yourself: what you’re working on, what you’re curious about, who you’d like to meet."
              : "What you’re working on, what you’re curious about, who you’d like to meet."
          }
          className="mt-2 min-h-[16rem] text-base leading-relaxed sm:min-h-[20rem]"
        />
      </label>

      <fieldset className="grid gap-4 sm:grid-cols-2">
        <legend className="mb-3 font-medium">The basics</legend>
        <Field
          label="Name"
          value={draft.profile.name}
          onChange={(value) => profile("name", value)}
          autoComplete="name"
        />
        <Field
          label="Based in"
          value={draft.profile.basedIn}
          onChange={(value) => profile("basedIn", value)}
          placeholder="City or time zone"
        />
        <Field
          label="Here for"
          value={draft.profile.staying}
          onChange={(value) => profile("staying", value)}
          placeholder="e.g. weeks 2 and 3"
        />
        <Field
          label="Links"
          value={draft.profile.links}
          onChange={(value) => profile("links", value)}
          placeholder="Website, X, GitHub…"
        />
      </fieldset>

      <label className="block">
        <span className="font-medium">
          Standing instructions{" "}
          <span className="font-normal text-muted-foreground">(optional)</span>
        </span>
        <Textarea
          value={extraContext(draft)}
          onChange={(event) =>
            onChange(withExtraContext(draft, event.target.value))
          }
          placeholder="e.g. Nothing before 10am. I prefer small dinners to big mixers."
          className="mt-2 min-h-24"
        />
      </label>
    </div>
  )
}

function Field({
  label,
  value,
  onChange,
  ...rest
}: {
  label: string
  value: string
  onChange: (value: string) => void
} & Omit<React.ComponentProps<"input">, "value" | "onChange">) {
  return (
    <label className="block text-sm">
      <span className="text-muted-foreground">{label}</span>
      <Input
        className="mt-1.5"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        {...rest}
      />
    </label>
  )
}
