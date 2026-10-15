/** Local deterministic simulation only; no backend or invoice-issuance semantics. */
export const DEMO_VAT_BASIS_POINTS = 1350;
export const DEMO_DATE = "15 October 2026";
export const DEMO_DUE_DATE = "29 October 2026";
export const DEMO_INVOICE_NUMBER = "DEMO-2026-001";
export type InvoiceDraft = { subtotalCents: number; revision: number };
export function invoiceTotals(subtotalCents: number) {
  if (
    !Number.isSafeInteger(subtotalCents) ||
    subtotalCents < 100 ||
    subtotalCents > 1000000
  )
    throw new Error("Invalid demonstration amount");
  const vatCents = Math.floor(
    (subtotalCents * DEMO_VAT_BASIS_POINTS + 5000) / 10000,
  );
  return { subtotalCents, vatCents, totalCents: subtotalCents + vatCents };
}
export function euros(cents: number) {
  return new Intl.NumberFormat("en-IE", {
    style: "currency",
    currency: "EUR",
  }).format(cents / 100);
}
export function parseAmount(value: string): number | null {
  if (!/^\d{1,5}(\.\d{1,2})?$/.test(value.trim())) return null;
  const [whole, fraction = ""] = value.trim().split(".");
  const cents = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  return cents >= 100 && cents <= 1000000 ? cents : null;
}
export type Message = { sender: "tara" | "you"; text: string };
export type DemoState = {
  phase: "idle" | "typing" | "draft" | "approved";
  draft: InvoiceDraft;
  reviewedRevision: number | null;
  messages: Message[];
  pendingReply: string | null;
};
export const initialDemoState: DemoState = {
  phase: "idle",
  draft: { subtotalCents: 45000, revision: 1 },
  reviewedRevision: null,
  messages: [
    {
      sender: "tara",
      text: "Hi, I’m Tara. Finished a job? Let’s get a draft invoice ready for you to check.",
    },
  ],
  pendingReply: null,
};
export type DemoAction =
  | { type: "request" }
  | { type: "reply" }
  | { type: "review"; revision: number }
  | { type: "correct"; subtotalCents: number }
  | { type: "approve"; revision: number }
  | { type: "reset" };
export function demoReducer(state: DemoState, action: DemoAction): DemoState {
  switch (action.type) {
    case "reset":
      return initialDemoState;
    case "request":
      if (state.phase !== "idle") return state;
      return {
        ...state,
        phase: "typing",
        messages: [
          ...state.messages,
          {
            sender: "you",
            text: "Tara, invoice John Murphy €450 for replacing his shower.",
          },
        ],
        pendingReply:
          "No problem. I’ve prepared a draft invoice for John Murphy. Would you like to review it?",
      };
    case "reply":
      if (state.phase !== "typing" || !state.pendingReply) return state;
      return {
        ...state,
        phase: "draft",
        pendingReply: null,
        messages: [
          ...state.messages,
          { sender: "tara", text: state.pendingReply },
        ],
      };
    case "review":
      return state.phase === "draft" && action.revision === state.draft.revision
        ? { ...state, reviewedRevision: action.revision }
        : state;
    case "correct":
      if (
        state.phase !== "draft" ||
        state.reviewedRevision !== state.draft.revision ||
        action.subtotalCents === state.draft.subtotalCents ||
        parseAmount((action.subtotalCents / 100).toFixed(2)) !==
          action.subtotalCents
      )
        return state;
      return {
        ...state,
        phase: "typing",
        draft: {
          subtotalCents: action.subtotalCents,
          revision: state.draft.revision + 1,
        },
        reviewedRevision: null,
        messages: [
          ...state.messages,
          {
            sender: "you",
            text: `Actually, change the amount to ${euros(action.subtotalCents)}.`,
          },
        ],
        pendingReply: `Updated. The invoice is now ${euros(action.subtotalCents)} before any applicable VAT. Please review this updated draft before approving it.`,
      };
    case "approve":
      if (
        state.phase !== "draft" ||
        state.reviewedRevision !== state.draft.revision ||
        action.revision !== state.draft.revision
      )
        return state;
      return {
        ...state,
        phase: "approved",
        messages: [
          ...state.messages,
          {
            sender: "you",
            text: `Yes, approve draft v${action.revision} for ${euros(invoiceTotals(state.draft.subtotalCents).totalCents)} including illustrative VAT.`,
          },
          {
            sender: "tara",
            text: "Your sample invoice is approved and finalised in this demonstration. You can download the sample PDF. Nothing has been issued, sent or charged.",
          },
        ],
      };
  }
}
