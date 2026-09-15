"use client";

// The developer panel: the real agent graph as a mermaid diagram, the current
// node lit up, and a run-through animation over the nodes the graph crossed
// between two pauses.
//
// It renders exactly when the backend sends a `debug` block, and the backend
// sends one exactly when it runs with DEBUG=true — production, where DEBUG is
// off, cannot show this panel no matter what the frontend does. The mermaid
// library itself is imported lazily for the same reason: without a debug block
// the import never happens, so the ~half-megabyte dependency never reaches a
// production visitor.
//
// The diagram is hand-written so the edges carry human labels, and it is kept
// honest by tests on both sides of the wire: the backend asserts the compiled
// graph has exactly the nodes listed in GRAPH_NODE_IDS, the frontend asserts
// the diagram mentions every one of them. Rename a node and both go red.
//
// Deliberately not translated: a developer tool speaks the codebase's language.

import { ChevronDown, CircuitBoard } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

export type AgentDebug = {
  node: string;
  rounds: number;
  asked: number;
  candidates_open: number;
  total_eur: number;
  pauschbetrag_eur: number;
  revision_round: number;
  findings: number;
  stop_declined: boolean;
  carried_over: number;
  last_decision: {
    kind: string;
    from_model: boolean;
    forced_gate?: boolean;
    question_id?: string;
  } | null;
};

// Must equal the node names of the compiled graph in agents/graph.py — the
// backend test test_the_panel_and_the_graph_agree_on_the_nodes pins that.
export const GRAPH_NODE_IDS = [
  "decide_next",
  "ask_user",
  "confirm_stop",
  "build_expenses",
  "review",
  "resolve_findings",
  "final_approval",
  "finalized",
] as const;

export const MERMAID_SOURCE = `flowchart TB
  decide_next["decide_next<br/><small>Interviewer decides</small>"]
  ask_user(["ask_user<br/><small>⏸ question</small>"])
  confirm_stop(["confirm_stop<br/><small>⏸ stop proposal</small>"])
  build_expenses["build_expenses<br/><small>calculators, plain code</small>"]
  review["review<br/><small>Reviewer agent</small>"]
  resolve_findings(["resolve_findings<br/><small>⏸ findings</small>"])
  final_approval(["final_approval<br/><small>⏸ approve</small>"])
  finalized(("finalized"))

  decide_next -->|"ask"| ask_user
  ask_user -->|"answer / don't know"| decide_next
  decide_next -->|"propose stop<br/>(gates answered)"| confirm_stop
  confirm_stop -->|"declined:<br/>filter picks next"| decide_next
  confirm_stop -->|"confirmed"| build_expenses
  build_expenses --> review
  review -->|"blocking"| resolve_findings
  review -->|"clean / warnings"| final_approval
  resolve_findings -->|"revise (≤ 2)"| decide_next
  resolve_findings -->|"dismiss / cap"| final_approval
  final_approval -->|"approved"| finalized
  final_approval -->|"declined"| decide_next

  classDef paused stroke-dasharray:5 5;
  class ask_user,confirm_stop,resolve_findings,final_approval paused;
`;

// The same edges as the diagram, for the run-through animation: the graph
// crosses non-pause nodes inside a single request, so their traversal is
// reconstructed here, not observed.
const EDGES: Record<string, string[]> = {
  decide_next: ["ask_user", "confirm_stop"],
  ask_user: ["decide_next"],
  confirm_stop: ["build_expenses", "decide_next"],
  build_expenses: ["review"],
  review: ["resolve_findings", "final_approval"],
  resolve_findings: ["decide_next", "final_approval"],
  final_approval: ["finalized", "decide_next"],
  finalized: [],
};

export function pathBetween(from: string, to: string): string[] {
  if (!from || from === to) return [to];
  const queue: string[][] = [[from]];
  const seen = new Set([from]);
  while (queue.length) {
    const path = queue.shift()!;
    for (const next of EDGES[path[path.length - 1]] ?? []) {
      if (seen.has(next)) continue;
      const grown = [...path, next];
      if (next === to) return grown.slice(1);
      seen.add(next);
      queue.push(grown);
    }
  }
  return [to];
}

const STEP_MS = 340;

/** A CSS colour as `#rrggbb`, whatever colour space it was written in.
 *
 * The design tokens are `oklch()`, which the browser hands back as `lab(...)`, and
 * mermaid's colour library understands neither: it throws `Unsupported color format`
 * and the diagram never draws. That is exactly what happened here — the panel showed
 * its statistics and an empty box for as long as it existed, because the throw was
 * caught and dropped.
 *
 * Painting the colour into a one-pixel canvas and reading the pixel back is the
 * conversion, and it works for any colour the browser can render at all, present
 * colour spaces and future ones alike.
 */
function toHex(value: string): string | null {
  if (!value) return null;
  if (/^#[0-9a-f]{3,8}$/i.test(value)) return value;
  try {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return null;
    ctx.fillStyle = "#000";
    ctx.fillStyle = value;
    ctx.fillRect(0, 0, 1, 1);
    const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
    return "#" + [r, g, b].map((c) => c.toString(16).padStart(2, "0")).join("");
  } catch {
    return null;
  }
}

export function AgentGraphPanel({
  debug,
  busy,
  liveNode,
}: {
  debug: AgentDebug | null;
  busy: boolean;
  // The node the SSE stream says the graph is in right now; overrides the
  // reconstruction while a request is in flight.
  liveNode?: string | null;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [active, setActive] = useState<string>("decide_next");
  const [drawError, setDrawError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const previousRef = useRef<string>("decide_next");

  const target = liveNode ?? (busy ? "decide_next" : (debug?.node ?? "decide_next"));

  // The run-through: step across the reconstructed path, one node at a time.
  useEffect(() => {
    const steps = pathBetween(previousRef.current, target);
    previousRef.current = target;
    if (steps.length <= 1) {
      setActive(target);
      return;
    }
    let index = 0;
    setActive(steps[0]);
    const timer = setInterval(() => {
      index += 1;
      if (index >= steps.length) {
        clearInterval(timer);
        return;
      }
      setActive(steps[index]);
    }, STEP_MS);
    return () => clearInterval(timer);
  }, [target]);

  // Render the diagram whenever the active node moves. Mermaid has no update
  // API; a full re-render of a graph this size takes ~50ms, below what the eye
  // reads as flicker.
  useEffect(() => {
    if (!debug || collapsed) return;
    let cancelled = false;

    (async () => {
      const mermaid = (await import("mermaid")).default;
      const css = getComputedStyle(document.documentElement);
      const token = (name: string, fallback: string) =>
        toHex(css.getPropertyValue(name).trim()) || fallback;

      mermaid.initialize({
        startOnLoad: false,
        securityLevel: "loose",
        theme: "base",
        themeVariables: {
          primaryColor: token("--surface", "#fff"),
          primaryTextColor: token("--foreground", "#111"),
          primaryBorderColor: token("--border-strong", "#bbb"),
          lineColor: token("--muted-foreground", "#888"),
          fontFamily: "ui-monospace, monospace",
          fontSize: "12px",
        },
        flowchart: { curve: "basis", padding: 6 },
      });

      // Both are plain hex by now, so the soft fill is a hex alpha suffix rather
      // than a color-mix() that mermaid would have to parse.
      const accent = token("--primary", "#4646d8");
      const accentSoft = `${accent}22`;
      const source =
        MERMAID_SOURCE +
        `  classDef active fill:${accentSoft},stroke:${accent},stroke-width:2.5px;\n` +
        `  class ${active} active;\n`;

      const { svg } = await mermaid.render(`agent-graph-${Date.now()}`, source);
      if (!cancelled && containerRef.current) {
        containerRef.current.innerHTML = svg;
        setDrawError(null);
      }
    })().catch((exc) => {
      // A diagram that fails to draw must never break the interview beside it —
      // but it must not fail in silence either. Swallowing this is how the panel
      // spent its life showing a stats list and an empty box: the render threw,
      // nobody heard it, and the diagram the panel exists for was simply absent.
      console.error("agent graph failed to render", exc);
      if (!cancelled) setDrawError(exc instanceof Error ? exc.message : String(exc));
    });

    return () => {
      cancelled = true;
    };
  }, [debug, active, collapsed]);

  if (!debug) return null;

  const decision = debug.last_decision;
  const decisionLabel = !decision
    ? "none yet"
    : decision.forced_gate
      ? "gate guard (code veto)"
      : decision.from_model
        ? "model"
        : "filter (fallback)";

  return (
    // In the flow, under the interview, and never floating. It used to be fixed to
    // the right, which cannot work beside a centred column: at 1280 it sat on top of
    // the card and swallowed clicks meant for it, and at 1680 it still clipped the
    // edge. Nobody noticed while the diagram was failing to draw and the panel was
    // four lines tall. In the flow it also gets the full column width, which is the
    // difference between a diagram you can read and one you squint at.
    <aside
      aria-label="Agent graph (developer panel)"
      className="print-hide mt-6 hidden w-full rounded-xl border border-border bg-surface p-4 md:block"
    >
      <button
        type="button"
        onClick={() => setCollapsed((value) => !value)}
        className="flex w-full items-center gap-2 text-xs font-medium uppercase tracking-wider text-muted-foreground"
      >
        <CircuitBoard className="size-3.5" aria-hidden="true" />
        Agent graph
        <span className="rounded bg-warning/20 px-1.5 py-0.5 text-[10px] normal-case tracking-normal">
          DEBUG
        </span>
        <ChevronDown
          aria-hidden="true"
          className={cn("ml-auto size-3.5 transition-transform", collapsed ? "-rotate-90" : "")}
        />
      </button>

      {!collapsed ? (
        <>
          <div
            ref={containerRef}
            className="agent-graph mt-3 max-h-[48vh] overflow-auto rounded-lg border border-border/60 bg-background/40 p-1"
          />
          {drawError ? (
            <p className="mt-1 text-[10px] text-destructive">diagram: {drawError}</p>
          ) : null}
        </>
      ) : null}

      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 border-t border-border pt-3 text-[11px]">
        <dt className="text-muted-foreground">last decision</dt>
        <dd className={cn("text-right font-mono", decision?.forced_gate ? "text-warning" : "")}>
          {decisionLabel}
        </dd>
        <dt className="text-muted-foreground">rounds</dt>
        <dd className="text-right font-mono">{debug.rounds} / 40</dd>
        <dt className="text-muted-foreground">asked / open</dt>
        <dd className="text-right font-mono">
          {debug.asked} / {debug.candidates_open}
        </dd>
        <dt className="text-muted-foreground">total vs allowance</dt>
        <dd className="text-right font-mono">
          {debug.total_eur.toFixed(0)} / {debug.pauschbetrag_eur.toFixed(0)} €
        </dd>
        {debug.revision_round > 0 ? (
          <>
            <dt className="text-muted-foreground">revisions</dt>
            <dd className="text-right font-mono">{debug.revision_round} / 2</dd>
          </>
        ) : null}
        {debug.findings > 0 ? (
          <>
            <dt className="text-muted-foreground">findings</dt>
            <dd className="text-right font-mono">{debug.findings}</dd>
          </>
        ) : null}
        {debug.carried_over > 0 ? (
          <>
            <dt className="text-muted-foreground">carried over</dt>
            <dd className="text-right font-mono">{debug.carried_over} not asked</dd>
          </>
        ) : null}
        {debug.stop_declined ? (
          <>
            <dt className="text-muted-foreground">stop declined</dt>
            <dd className="text-right font-mono">next pick: filter</dd>
          </>
        ) : null}
      </dl>
    </aside>
  );
}
