"use client";
import Link from "next/link";
import { useReducer, useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  Check,
  CheckCheck,
  FileText,
  MoreVertical,
  RotateCcw,
  Send,
  ShieldCheck,
  Signal,
  BatteryFull,
  Wifi,
  X,
  Pencil,
  Download,
} from "lucide-react";
import {
  demoReducer,
  initialDemoState,
  euros,
  invoiceTotals,
  parseAmount,
} from "@/lib/tara-demo";
import { downloadSampleInvoice } from "@/lib/invoice-pdf";
import InvoicePreview from "./invoice-preview";
export default function Demo() {
  const [state, dispatch] = useReducer(demoReducer, initialDemoState);
  const [editing, setEditing] = useState(false);
  const [amount, setAmount] = useState("500");
  const [error, setError] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const chat = useRef<HTMLDivElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const amountInput = useRef<HTMLInputElement>(null);
  const busy = state.phase === "typing";
  const approved = state.phase === "approved";
  const hasDraft = state.phase === "draft" || approved;
  const reviewed = state.reviewedRevision === state.draft.revision;
  const totals = invoiceTotals(state.draft.subtotalCents);
  useEffect(() => {
    if (!busy) return;
    const timer = setTimeout(() => dispatch({ type: "reply" }), 700);
    return () => clearTimeout(timer);
  }, [busy]);
  useEffect(() => {
    if (chat.current)
      chat.current.scrollTop =
        state.phase === "idle" ? 0 : chat.current.scrollHeight;
  }, [state.messages.length, state.phase]);
  useEffect(() => {
    if (editing) amountInput.current?.focus();
  }, [editing]);
  useEffect(() => {
    if (!modalOpen) return;
    const before = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = before;
    };
  }, [modalOpen]);
  function openInvoice(event: React.MouseEvent<HTMLButtonElement>) {
    opener.current = event.currentTarget;
    dispatch({ type: "review", revision: state.draft.revision });
    setEditing(false);
    setError("");
    dialog.current?.showModal();
    setModalOpen(true);
  }
  function closeInvoice() {
    dialog.current?.close();
    setModalOpen(false);
    opener.current?.focus();
  }
  function correct(cents: number) {
    dispatch({ type: "correct", subtotalCents: cents });
    closeInvoice();
    setEditing(false);
    setError("");
  }
  function applyAmount(event: FormEvent) {
    event.preventDefault();
    const cents = parseAmount(amount);
    if (cents === null) {
      setError(
        "Enter an amount from €1 to €10,000, with up to two decimal places.",
      );
      amountInput.current?.focus();
      return;
    }
    if (cents === state.draft.subtotalCents) {
      setError("Choose a different amount to demonstrate a correction.");
      return;
    }
    correct(cents);
  }
  function approve() {
    dispatch({ type: "approve", revision: state.draft.revision });
    closeInvoice();
  }
  function reset() {
    closeInvoice();
    dispatch({ type: "reset" });
    setEditing(false);
    setError("");
    setAmount("500");
  }
  return (
    <div className="tara-demo" id="demo">
      <div className="demo-topline">
        <span>
          <i /> INTERACTIVE PRODUCT PREVIEW
        </span>
        <button
          onClick={reset}
          className="demo-restart"
          aria-label="Restart demonstration"
        >
          <RotateCcw size={13} />
          Restart
        </button>
      </div>
      <div className="tara-stage">
        <div className="tara-phone">
          <div className="phone-status">
            <span>9:41</span>
            <span className="phone-signals">
              <Signal size={12} />
              <Wifi size={12} />
              <BatteryFull size={16} />
            </span>
          </div>
          <div className="tara-chat-header">
            <ArrowLeft size={18} aria-hidden="true" />
            <div className="avatar">T</div>
            <div>
              <strong>Tara</strong>
              <span>An Oifig · Demo assistant</span>
            </div>
            <MoreVertical size={19} aria-hidden="true" />
          </div>
          <div
            ref={chat}
            className="tara-chat"
            role="region"
            aria-label="Tara demonstration conversation"
            tabIndex={0}
          >
            <div className="chat-day">TODAY</div>
            <div className="simulation-label">
              Simulated conversation · fictional details
            </div>
            {state.messages.map((message, i) => (
              <div
                key={i}
                className={`tara-message ${message.sender === "you" ? "sent" : "received"}`}
              >
                <span>{message.text}</span>
                <small>
                  9:{String(41 + Math.floor(i / 2)).padStart(2, "0")}{" "}
                  {message.sender === "you" && (
                    <CheckCheck size={12} aria-hidden="true" />
                  )}
                </small>
              </div>
            ))}
            {state.phase === "idle" && (
              <div className="tara-message sent suggested-message">
                <span>
                  Tara, invoice John Murphy €450 for replacing his shower.
                </span>
                <small>Ready to try · not sent</small>
              </div>
            )}
            {busy && (
              <div
                className="typing-indicator"
                role="status"
                aria-label="Tara is typing"
              >
                <span />
                <span />
                <span />
              </div>
            )}
            {hasDraft && (
              <button
                className={`chat-document ${approved ? "is-approved" : ""}`}
                onClick={openInvoice}
              >
                <div className="chat-document-icon">
                  <FileText size={25} />
                  <span>PDF</span>
                </div>
                <div>
                  <strong>
                    {approved
                      ? "Approved sample invoice"
                      : "Review your invoice draft"}
                  </strong>
                  <span>John Murphy · v{state.draft.revision}</span>
                  <b>
                    {euros(totals.totalCents)}{" "}
                    <small>incl. illustrative VAT</small>
                  </b>
                </div>
                <ArrowUpRight size={16} />
              </button>
            )}
            {approved && (
              <div className="approval-receipt">
                <ShieldCheck size={15} />
                You approved v{state.draft.revision}. No delivery took place.
              </div>
            )}
          </div>
          <div className="tara-composer">
            <span>
              {state.phase === "idle"
                ? "Tara, invoice John Murphy €450…"
                : busy
                  ? "Tara is preparing your draft…"
                  : approved
                    ? "One less thing on your list."
                    : "Choose your next step below"}
            </span>
            <Send size={17} aria-hidden="true" />
          </div>
        </div>
        <div className="demo-side-note">
          <span className="demo-note-line" />
          <ShieldCheck size={20} />
          <strong>
            Your invoice.
            <br />
            Your final say.
          </strong>
          <p>
            Review, correct,
            <br />
            then approve.
          </p>
        </div>
      </div>
      <div className="tara-actions" aria-label="Demonstration controls">
        {state.phase === "idle" ? (
          <button
            className="button gold"
            onClick={() => dispatch({ type: "request" })}
          >
            Send invoice request <Send size={16} />
          </button>
        ) : busy ? (
          <button className="button gold" disabled>
            Preparing your draft…
          </button>
        ) : approved ? (
          <>
            <button
              className="button gold"
              onClick={() => downloadSampleInvoice(state.draft)}
            >
              Download sample PDF <Download size={16} />
            </button>
            <Link className="demo-conversion" href="/early-access">
              Want this in your working day? Get early access{" "}
              <ArrowUpRight size={14} />
            </Link>
          </>
        ) : (
          <>
            <button className="button gold" onClick={openInvoice}>
              {reviewed ? "Review current draft" : "Review invoice draft"}{" "}
              <FileText size={16} />
            </button>
            {reviewed && (
              <div className="demo-secondary-actions">
                <button
                  onClick={() => {
                    if (state.draft.subtotalCents !== 50000) correct(50000);
                    else {
                      setEditing(true);
                      setError("");
                      dialog.current?.showModal();
                      setModalOpen(true);
                    }
                  }}
                >
                  <Pencil size={14} />
                  {state.draft.subtotalCents !== 50000
                    ? "Change amount to €500"
                    : "Change amount"}
                </button>
                <button onClick={approve}>
                  Approve v{state.draft.revision} <Check size={14} />
                </button>
              </div>
            )}
          </>
        )}
      </div>
      <p className="tara-demo-caption" role="status">
        {approved
          ? "Sample complete. No invoice sent."
          : state.phase === "idle"
            ? "Try it yourself. Start with the message above."
            : busy
              ? "Tara is typing…"
              : reviewed
                ? "Make a correction or approve the version you reviewed."
                : "Your draft is ready. Open it to check the details."}
      </p>
      <dialog
        className="invoice-dialog"
        ref={dialog}
        aria-labelledby="invoice-dialog-title"
        onCancel={() => setModalOpen(false)}
        onClose={() => {
          setModalOpen(false);
          opener.current?.focus();
        }}
        onClick={(e) => {
          if (e.target === e.currentTarget) closeInvoice();
        }}
      >
        <div className="invoice-dialog-bar">
          <div>
            <span>DEMONSTRATION DOCUMENT</span>
            <h2 id="invoice-dialog-title">
              {approved ? "Your approved sample" : "Check your invoice draft"}{" "}
              <small>v{state.draft.revision}</small>
            </h2>
          </div>
          <button
            className="icon-button"
            aria-label="Close invoice preview"
            onClick={closeInvoice}
          >
            <X size={22} />
          </button>
        </div>
        {modalOpen && (
          <InvoicePreview draft={state.draft} approved={approved} />
        )}
        <div className="invoice-dialog-actions">
          {approved ? (
            <button
              className="button"
              onClick={() => downloadSampleInvoice(state.draft)}
            >
              Download sample PDF <Download size={16} />
            </button>
          ) : editing ? (
            <form onSubmit={applyAmount} noValidate>
              <label htmlFor="invoice-amount">Amount before VAT (€)</label>
              <div className="amount-row">
                <input
                  ref={amountInput}
                  id="invoice-amount"
                  inputMode="decimal"
                  value={amount}
                  onChange={(e) => {
                    setAmount(e.target.value);
                    setError("");
                  }}
                  aria-invalid={!!error}
                  aria-describedby={error ? "amount-error" : "amount-help"}
                />
                <button className="button" type="submit">
                  Update draft
                </button>
              </div>
              <p id="amount-help">
                Illustrative VAT is recalculated automatically.
              </p>
              {error && (
                <p id="amount-error" role="alert">
                  {error}
                </p>
              )}
            </form>
          ) : (
            <>
              <button
                className="button outline"
                onClick={() => {
                  setAmount(
                    state.draft.subtotalCents === 45000
                      ? "500"
                      : (state.draft.subtotalCents / 100).toFixed(2),
                  );
                  setEditing(true);
                }}
              >
                <Pencil size={16} />
                Change amount
              </button>
              <button className="button" onClick={approve}>
                Approve v{state.draft.revision} · {euros(totals.totalCents)}{" "}
                <Check size={16} />
              </button>
            </>
          )}
          <p>
            Approval is simulated and applies only to the draft version shown
            above.
          </p>
        </div>
      </dialog>
    </div>
  );
}
