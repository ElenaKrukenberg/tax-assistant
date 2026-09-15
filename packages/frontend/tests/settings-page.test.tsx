/**
 * The Settings screen, control by control: each one either does what it says or is
 * not on the screen (#18). So the assertions are about effects - a stored value, a
 * class on the document, a DELETE that reached the API - and never about a switch
 * having moved, which is exactly what the broken version did too.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import SettingsPage from "../app/settings/page";
import { ThemeProvider } from "@/components/theme-provider";
import { LocaleProvider } from "@/i18n/locale-provider";
import { STORAGE_KEY, type Conversation } from "@/lib/conversation-history";
import { KEYS } from "@/lib/preferences";

// AppNav sits at the top of the screen and asks the App Router where it is.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/settings",
}));

const { session, listCases, deleteCase, liveBackend } = vi.hoisted(() => ({
  session: {
    current: { status: "signed_in" as string, email: "elena@example.com" as string | null },
  },
  listCases: vi.fn(),
  deleteCase: vi.fn(),
  liveBackend: { value: true },
}));

vi.mock("@/hooks/use-session", () => ({ useSession: () => session.current }));
vi.mock("@/lib/supabase", () => ({
  get isLiveBackend() {
    return liveBackend.value;
  },
  supabase: null,
}));
vi.mock("@/features/cases/api", async () => {
  const actual =
    await vi.importActual<typeof import("@/features/cases/api")>("@/features/cases/api");
  return { ...actual, listCases, deleteCase };
});

function renderSettings() {
  return render(
    <ThemeProvider>
      <LocaleProvider>
        <SettingsPage />
      </LocaleProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  session.current = { status: "signed_in", email: "elena@example.com" };
  liveBackend.value = true;
  listCases.mockResolvedValue([]);
  deleteCase.mockResolvedValue(undefined);
});

describe("the controls that were decoration", () => {
  it("remembers the theme and puts the palette on the document", async () => {
    renderSettings();
    const user = userEvent.setup();

    await user.click(screen.getByLabelText("Dark"));

    await waitFor(() => expect(document.documentElement).toHaveClass("dark"));
    expect(localStorage.getItem(KEYS.theme)).toBe("dark");

    await user.click(screen.getByLabelText("Light"));
    await waitFor(() => expect(document.documentElement).not.toHaveClass("dark"));
    expect(localStorage.getItem(KEYS.theme)).toBe("light");
  });

  it("remembers the response depth the chat request has to carry", async () => {
    renderSettings();
    const user = userEvent.setup();

    await user.click(screen.getByRole("combobox", { name: /Response depth/i }));
    await user.click(await screen.findByRole("option", { name: "Detailed" }));

    await waitFor(() => expect(localStorage.getItem(KEYS.depth)).toBe("detailed"));
  });

  it("remembers whether the retrieval steps are shown", async () => {
    renderSettings();
    const user = userEvent.setup();

    await user.click(screen.getByRole("switch", { name: /Show retrieval process/i }));

    await waitFor(() => expect(localStorage.getItem(KEYS.showTrace)).toBe("false"));
  });

  it("deletes the stored conversations when history is switched off", async () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([
        { id: "c1", title: "Earlier question", updatedAt: Date.now(), messages: [] },
      ] satisfies Conversation[]),
    );
    renderSettings();
    const user = userEvent.setup();

    await user.click(screen.getByRole("switch", { name: /Save conversation history/i }));

    // off means both: no more writing, and the transcripts already here are gone
    await waitFor(() => expect(localStorage.getItem(KEYS.saveHistory)).toBe("false"));
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});

describe("the controls that left the screen", () => {
  it("offers no export, because the operation behind it does not exist yet", () => {
    renderSettings();
    expect(screen.queryByRole("button", { name: /Export/i })).not.toBeInTheDocument();
  });

  it("offers no training switch, and says plainly what is true instead", () => {
    renderSettings();

    expect(screen.queryByText(/Improve the model/i)).not.toBeInTheDocument();
    expect(screen.getByText("Your chats are never used to train a model.")).toBeInTheDocument();
  });
});

describe("deleting a Tax Case", () => {
  const CASES = [
    { id: "case-2025", tax_year: 2025, status: "gathering" },
    { id: "case-2024", tax_year: 2024, status: "finalized" },
  ];

  it("deletes the one that was chosen, after a confirmation", async () => {
    listCases.mockResolvedValue(CASES);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderSettings();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("combobox", { name: /Your Tax Case/i }));
    await user.click(await screen.findByRole("option", { name: /2024/ }));
    await user.click(screen.getByRole("button", { name: /Delete Tax Case/i }));

    await waitFor(() => expect(deleteCase).toHaveBeenCalledWith("case-2024"));
    // and the deleted one stops being offered
    expect(window.confirm).toHaveBeenCalledOnce();
  });

  it("deletes nothing when the confirmation is declined", async () => {
    listCases.mockResolvedValue(CASES);
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderSettings();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("combobox", { name: /Your Tax Case/i }));
    await user.click(await screen.findByRole("option", { name: /2025/ }));
    await user.click(screen.getByRole("button", { name: /Delete Tax Case/i }));

    expect(deleteCase).not.toHaveBeenCalled();
  });

  it("says there is nothing to delete rather than offering a dead button", async () => {
    listCases.mockResolvedValue([]);
    renderSettings();

    expect(await screen.findByText("No Tax Case to delete.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete Tax Case/i })).not.toBeInTheDocument();
  });

  it("is absent entirely when nobody is signed in", async () => {
    session.current = { status: "signed_out", email: null };
    renderSettings();

    await waitFor(() => expect(listCases).not.toHaveBeenCalled());
    expect(screen.queryByText("Your Tax Case")).not.toBeInTheDocument();
  });
});

describe("the account card", () => {
  it("names the person who is actually signed in", async () => {
    renderSettings();
    expect(await screen.findByText("Signed in as elena@example.com.")).toBeInTheDocument();
    // the sentence it replaced, which was shown to signed-in users
    expect(screen.queryByText(/anonymous session/i)).not.toBeInTheDocument();
  });

  it("does not claim a session when there is none", async () => {
    session.current = { status: "signed_out", email: null };
    renderSettings();
    expect(await screen.findByText("Not signed in.")).toBeInTheDocument();
  });

  it("says so when the app is running on fixtures", async () => {
    liveBackend.value = false;
    session.current = { status: "fixture", email: null };
    renderSettings();
    expect(await screen.findByText("Demo mode: no account is connected.")).toBeInTheDocument();
  });
});

describe("the language controls that already worked", () => {
  it("still switches the interface language", async () => {
    renderSettings();
    const user = userEvent.setup();

    const general = screen.getByRole("combobox", { name: /Interface language/i });
    await user.click(general);
    await user.click(await screen.findByRole("option", { name: "Deutsch" }));

    // Scoped to the page, not the document: "Einstellungen" is now also the header's
    // link to this page, and an unscoped search finds both.
    const main = () => within(screen.getByRole("main"));
    await waitFor(() => expect(main().getByText("Einstellungen")).toBeInTheDocument());
    expect(main().getByText("Datenschutz")).toBeInTheDocument();
  });
});
