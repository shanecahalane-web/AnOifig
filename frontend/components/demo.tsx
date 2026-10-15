"use client";
import { useState, useEffect, useRef } from "react";
import {
  ArrowLeft,
  Check,
  CheckCheck,
  FileText,
  LockKeyhole,
  MoreVertical,
  RotateCcw,
  Send,
  Sparkles,
} from "lucide-react";
const stages = [
  {
    label: "Ask for an invoice",
    user: "Tara, can you draft an invoice for the bathroom job for Aoife Murphy?",
    reply:
      "Of course. What work should I include, and what’s the agreed amount?",
  },
  {
    label: "Add the details",
    user: "Bathroom tiling, labour only. €800 total. Due in 14 days, please.",
    reply: "Thanks. Here’s a draft for you to check. Nothing has been sent.",
  },
  {
    label: "Approve the draft",
    user: "I’ve checked the details. Approve this draft.",
    reply:
      "Draft approved. The approved document is ready for you to download. In this demo, no invoice is issued or sent.",
  },
];
export default function Demo() {
  const [step, setStep] = useState(0);
  const chat = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (chat.current)
      chat.current.scrollTop = step === 0 ? 0 : chat.current.scrollHeight;
  }, [step]);
  return (
    <div className="demo-wrap">
      <div className="phone">
        <div className="phone-status">
          <span>9:41</span>
          <span>▮▮▮ &nbsp; ▰</span>
        </div>
        <div className="chat-header">
          <ArrowLeft size={19} />
          <div className="avatar">T</div>
          <div className="chat-name">
            <strong>Tara</strong>
            <span>Your An Oifig assistant</span>
          </div>
          <MoreVertical size={20} />
        </div>
        <div
          className="chat-body"
          ref={chat}
          role="region"
          aria-label="Tara demonstration conversation"
          tabIndex={0}
        >
          <div className="chat-date">TODAY · DEMONSTRATION</div>
          <div className="chat-security">
            <LockKeyhole size={12} /> A preview of how Tara could help.
          </div>
          <div className="bubble incoming">
            Hi there. Let’s get that paperwork off your list. What can I help
            with?
          </div>
          {stages.slice(0, step).map((s, i) => (
            <div className="conversation" key={i}>
              <div className="bubble outgoing">
                {s.user}
                <span className="message-time">
                  9:41 <CheckCheck size={13} />
                </span>
              </div>
              <div className="bubble incoming">{s.reply}</div>
              {i === 1 && (
                <div className="invoice">
                  <div className="invoice-heading">
                    <FileText size={22} />
                    <div>
                      <strong>Invoice draft</strong>
                      <span>DEMO-001 · For review</span>
                    </div>
                  </div>
                  <dl>
                    <div>
                      <dt>Customer</dt>
                      <dd>Aoife Murphy</dd>
                    </div>
                    <div>
                      <dt>Bathroom tiling · labour</dt>
                      <dd>€800.00</dd>
                    </div>
                    <div>
                      <dt>Payment due</dt>
                      <dd>14 days</dd>
                    </div>
                  </dl>
                  <div className="invoice-total">
                    <span>Draft total</span>
                    <strong>€800.00</strong>
                  </div>
                  <small>
                    Fictional data. Illustrative total; tax treatment not
                    assessed.
                  </small>
                </div>
              )}
              {i === 2 && (
                <div className="approved">
                  <Check size={16} /> Approval recorded · demo only
                </div>
              )}
            </div>
          ))}
        </div>
        <div className="chat-input">
          <span>
            {step < 3
              ? "Your next message is ready below…"
              : "All done. That’s one less thing."}
          </span>
          <Send size={17} />
        </div>
      </div>
      <div className="demo-controls">
        <button
          className="button"
          disabled={step === 3}
          onClick={() => setStep(step + 1)}
        >
          {step < 3 ? stages[step].label : "Demo complete"}{" "}
          {step < 3 ? <Send size={16} /> : <Check size={16} />}
        </button>
        <button
          className="reset"
          onClick={() => setStep(0)}
          aria-label="Restart demonstration"
        >
          <RotateCcw size={18} />
        </button>
      </div>
      <p className="demo-caption" aria-live="polite">
        Step {Math.min(step + 1, 3)} of 3 · Interactive simulation. No messages
        or documents are sent.
      </p>
    </div>
  );
}
