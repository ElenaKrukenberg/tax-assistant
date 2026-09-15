/**
 * The live Documents screen, on the path that has no upload in it: the user comes
 * back to a case where a document is already waiting for a decision.
 *
 * The proposed values are never stored - they live in the paused intake run and
 * reach the screen only because the list endpoint goes and reads them (ADR 0004).
 * So the fixture below is what the *list* answers, with nothing uploaded in this
 * render, and what is held is that the card is usable from that alone: the fields
 * are there, and confirming without typing sends the values the document proposed
 * rather than an empty body the backend would refuse.
 */

import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

import type { LiveDocument } from "@/features/cases/api";
import { LiveDocuments } from "@/components/cases/live-documents";
import { LocaleProvider } from "@/i18n/locale-provider";

const WAITING: LiveDocument = {
  id: "doc-1",
  file_name: "rechnung.jpg",
  kind: "rechnung",
  state: "awaiting_confirmation",
  proposed: [
    { key: "equipment.price_eur", value: 689, label: "What did the work equipment cost?", item: 1 },
    {
      key: "equipment.price_eur#2",
      value: 46.25,
      label: "What did the work equipment cost?",
      item: 3,
    },
  ],
  questions: [],
  disagreements: [],
  category: "arbeitsmittel",
  category_reason: "the invoice names schreibtisch",
  contradiction: null,
  category_choices: ["arbeitsmittel", "fortbildungskosten", "umzugskosten", "bewerbungskosten"],
  read_by: "google/gemini-3.7-flash",
  read_cost_usd: 0.0062,
  read_tokens: 2535,
  failure_code: null,
  failure_detail: null,
};

/** The other case: no line names a category, so nothing is proposed until one is. */
const UNPLACED: LiveDocument = {
  ...WAITING,
  proposed: [],
  questions: [
    "The category could not be decided from the document - no line on the invoice " +
      "names a known category. Choose it yourself.",
  ],
  category: null,
  category_reason: "",
};

/** What the backend answers once a category is picked: different keys, not a label. */
const RECLASSIFIED: LiveDocument = {
  ...UNPLACED,
  proposed: [
    { key: "education.amount_eur", value: 240, label: "What did the training cost?", item: null },
  ],
  questions: [],
  category: "fortbildungskosten",
  category_reason: "you chose this category",
};

const listDocuments = vi.fn(async () => [WAITING]);
const confirmDocument = vi.fn(async () => ({ ...WAITING, state: "confirmed" as const }));
const discardDocument = vi.fn(async () => ({ ...WAITING, state: "discarded" as const }));
const setDocumentCategory = vi.fn(async () => RECLASSIFIED);
const uploadDocument = vi.fn();

vi.mock("@/features/cases/api", () => ({
  ApiError: class ApiError extends Error {},
  listDocuments: (...args: unknown[]) => listDocuments(...(args as [])),
  confirmDocument: (...args: unknown[]) => confirmDocument(...(args as [])),
  discardDocument: (...args: unknown[]) => discardDocument(...(args as [])),
  setDocumentCategory: (...args: unknown[]) => setDocumentCategory(...(args as [])),
  uploadDocument: (...args: unknown[]) => uploadDocument(...(args as [])),
}));

async function renderScreen() {
  render(
    <LocaleProvider>
      <LiveDocuments caseId="case-1" />
    </LocaleProvider>,
  );
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("a document already waiting when the screen opens", () => {
  it("shows the values it is waiting to be asked about", async () => {
    await renderScreen();

    expect(screen.getByDisplayValue("689")).toBeInTheDocument();
    expect(screen.getByDisplayValue("46.25")).toBeInTheDocument();
    expect(screen.getByText(/the invoice names schreibtisch/)).toBeInTheDocument();
  });

  it("confirms what the document proposed when nothing was typed", async () => {
    await renderScreen();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /confirm/i }));
    });

    expect(confirmDocument).toHaveBeenCalledWith(
      "case-1",
      "doc-1",
      { "equipment.price_eur": 689, "equipment.price_eur#2": 46.25 },
      "arbeitsmittel",
    );
  });

  it("sends the correction instead, once one is typed", async () => {
    await renderScreen();

    fireEvent.change(screen.getByDisplayValue("689"), { target: { value: "700" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /confirm/i }));
    });

    expect(confirmDocument).toHaveBeenCalledWith(
      "case-1",
      "doc-1",
      { "equipment.price_eur": 700, "equipment.price_eur#2": 46.25 },
      "arbeitsmittel",
    );
  });
});

describe("an invoice the rules could not place", () => {
  it("offers the four categories and asks the backend for the one picked", async () => {
    listDocuments.mockResolvedValueOnce([UNPLACED]);
    await renderScreen();

    expect(screen.getByRole("radiogroup", { name: /which category/i })).toBeInTheDocument();
    const chosen = screen.getByRole("radio", { name: "Training costs" });

    await act(async () => {
      fireEvent.click(chosen);
    });

    expect(setDocumentCategory).toHaveBeenCalledWith("case-1", "doc-1", "fortbildungskosten");
  });

  it("replaces the fields with the ones the new category keys", async () => {
    listDocuments.mockResolvedValueOnce([UNPLACED]);
    await renderScreen();

    expect(screen.queryByDisplayValue("689")).not.toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("radio", { name: "Training costs" }));
    });

    expect(screen.getByDisplayValue("240")).toBeInTheDocument();
    expect(screen.getByLabelText(/What did the training cost\?/)).toBeInTheDocument();
  });

  it("offers no category where there is nothing to choose between", async () => {
    listDocuments.mockResolvedValueOnce([{ ...UNPLACED, category_choices: [] }]);
    await renderScreen();

    expect(screen.queryByRole("radiogroup", { name: /which category/i })).not.toBeInTheDocument();
  });
});

describe("what a field is called on the screen", () => {
  it("shows the catalogue's wording and not the Fact key", async () => {
    await renderScreen();

    expect(screen.getAllByText(/What did the work equipment cost\?/)).toHaveLength(2);
    expect(screen.queryByText("equipment.price_eur#2")).not.toBeInTheDocument();
  });

  it("numbers the repeated items so two prices are not the same field twice", async () => {
    await renderScreen();

    expect(screen.getByText("Item 1")).toBeInTheDocument();
    expect(screen.getByText("Item 3")).toBeInTheDocument();
    // The key is still the input's id, which is what the confirmation sends back.
    expect(document.getElementById("doc-1-equipment.price_eur#2")).not.toBeNull();
  });
});

describe("which model read the document", () => {
  it("names it, because the configured one is not always the one that answered", async () => {
    listDocuments.mockResolvedValueOnce([{ ...WAITING, read_by: "x-ai/grok-4.5" }]);
    await renderScreen();

    expect(screen.getByText("Read by x-ai/grok-4.5")).toBeInTheDocument();
  });
});
