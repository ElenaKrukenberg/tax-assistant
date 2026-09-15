import { describe, expect, it } from "vitest";

import { GRAPH_NODE_IDS, MERMAID_SOURCE, pathBetween } from "@/components/cases/agent-graph-panel";

// The other half of this contract lives in the backend:
// tests/test_graph.py::test_the_panel_and_the_graph_agree_on_the_nodes pins the
// compiled graph to the same node list. Rename a node and both suites go red.
describe("agent graph panel", () => {
  it("draws every node the real graph has", () => {
    for (const id of GRAPH_NODE_IDS) {
      expect(MERMAID_SOURCE).toContain(id);
    }
  });

  it("marks exactly the four interrupt nodes as paused", () => {
    const line = MERMAID_SOURCE.split("\n").find(
      (l) => l.trim().startsWith("class ") && l.includes("paused"),
    );
    expect(line).toContain("ask_user");
    expect(line).toContain("confirm_stop");
    expect(line).toContain("resolve_findings");
    expect(line).toContain("final_approval");
  });

  it("reconstructs the run-through between two pauses", () => {
    // Confirming a stop crosses two nodes nobody pauses on: the animation walks
    // build_expenses and review before settling on the gate.
    expect(pathBetween("confirm_stop", "final_approval")).toEqual([
      "build_expenses",
      "review",
      "final_approval",
    ]);
    expect(pathBetween("ask_user", "confirm_stop")).toEqual(["decide_next", "confirm_stop"]);
    expect(pathBetween("final_approval", "finalized")).toEqual(["finalized"]);
  });

  it("does not animate when nothing moved", () => {
    expect(pathBetween("ask_user", "ask_user")).toEqual(["ask_user"]);
    expect(pathBetween("", "ask_user")).toEqual(["ask_user"]);
  });
});
