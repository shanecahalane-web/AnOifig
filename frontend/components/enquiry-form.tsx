"use client";
import Link from "next/link";
import { useState, useRef, useId, type FormEvent } from "react";
import { ArrowUpRight, Check, CheckCircle2, ShieldCheck } from "lucide-react";
import {
  submitDemoEnquiry,
  validateEnquiry,
  type EnquiryErrors,
  type Enquiry,
} from "@/lib/enquiry";
export default function EnquiryForm({
  contact = false,
}: {
  contact?: boolean;
}) {
  const [errors, setErrors] = useState<EnquiryErrors>({});
  const [status, setStatus] = useState<
    "idle" | "submitting" | "done" | "error"
  >("idle");
  const form = useRef<HTMLFormElement>(null);
  const confirmation = useRef<HTMLDivElement>(null);
  const id = useId();
  function fieldId(key: string) {
    return `${id}-${key}`;
  }
  function props(key: keyof Enquiry) {
    return {
      id: fieldId(key),
      name: key,
      "aria-invalid": !!errors[key],
      "aria-describedby": errors[key] ? `${fieldId(key)}-error` : undefined,
    };
  }
  function error(key: keyof Enquiry) {
    return errors[key] ? (
      <span className="field-error" id={`${fieldId(key)}-error`}>
        {errors[key]}
      </span>
    ) : null;
  }
  function sample() {
    if (!form.current) return;
    const values = {
      name: "Alex Example",
      email: "demo@example.com",
      phone: "",
      message: contact
        ? "I’d like to understand how invoice corrections work."
        : "",
    };
    for (const [key, value] of Object.entries(values)) {
      const input = form.current.elements.namedItem(
        key,
      ) as HTMLInputElement | null;
      if (input) input.value = value;
    }
    const trade = form.current.elements.namedItem(
      "trade",
    ) as HTMLSelectElement | null;
    if (trade) trade.value = "Plumber";
    setErrors({});
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (status === "submitting") return;
    const data = new FormData(event.currentTarget);
    const value: Enquiry = {
      name: String(data.get("name") ?? "").trim(),
      email: String(data.get("email") ?? "").trim(),
      trade: String(data.get("trade") ?? ""),
      phone: String(data.get("phone") ?? "").trim(),
      message: String(data.get("message") ?? "").trim(),
      consent: data.get("consent") === "on",
    };
    const found = validateEnquiry(value, contact);
    setErrors(found);
    if (Object.keys(found).length) {
      const input = form.current?.elements.namedItem(
        Object.keys(found)[0],
      ) as HTMLElement | null;
      input?.focus();
      return;
    }
    setStatus("submitting");
    try {
      const result = await submitDemoEnquiry(value);
      if (result.mode !== "demo" || result.persisted !== false)
        throw new Error("Unexpected adapter result");
      form.current?.reset();
      setStatus("done");
      requestAnimationFrame(() => confirmation.current?.focus());
    } catch {
      setStatus("error");
    }
  }
  return (
    <div className="enquiry-card">
      <div className="form-card-heading">
        <span className="pill">DEMONSTRATION MODE</span>
        <ShieldCheck size={20} />
      </div>
      <h2>
        {contact ? "A message starts here." : "Make room for less admin."}
      </h2>
      <p className="form-intro">
        {contact
          ? "Try the contact experience with sample details."
          : "See how early-access signup will work."}
      </p>
      <div className="form-notice">
        <strong>No information is sent or saved.</strong>
        <p>
          Use fictional details to try this form. A secure destination, reviewed
          privacy notice and retention policy are required before real signup
          opens.
        </p>
      </div>
      {status === "done" ? (
        <div
          className="mock-confirmation"
          ref={confirmation}
          tabIndex={-1}
          role="status"
        >
          <CheckCircle2 size={32} />
          <h3>That’s the demo complete.</h3>
          <p>
            {contact
              ? "No message has been sent."
              : "You have not joined a waiting list."}{" "}
            Your sample details were cleared. No information was stored.
          </p>
          <button
            className="button outline"
            onClick={() => {
              setStatus("idle");
              setErrors({});
            }}
          >
            Try the form again
          </button>
          <Link href="/#demo">
            Back to Tara’s demonstration <ArrowUpRight size={15} />
          </Link>
        </div>
      ) : (
        <form
          ref={form}
          onSubmit={submit}
          noValidate
          className="enquiry-form"
          aria-label={
            contact ? "Contact demonstration" : "Early-access demonstration"
          }
        >
          <button className="sample-fill" type="button" onClick={sample}>
            Use sample details <ArrowUpRight size={13} />
          </button>
          {Object.keys(errors).length > 0 && (
            <div className="error-summary" role="alert">
              Please check{" "}
              {Object.keys(errors).length === 1
                ? "the highlighted field"
                : "the highlighted fields"}{" "}
              below.
            </div>
          )}
          <div className="form-field">
            <label htmlFor={fieldId("name")}>Name</label>
            <input
              {...props("name")}
              required
              autoComplete="off"
              maxLength={120}
              placeholder="Alex Example"
            />
            {error("name")}
          </div>
          <div className="form-field">
            <label htmlFor={fieldId("email")}>Email address</label>
            <input
              {...props("email")}
              type="email"
              required
              autoComplete="off"
              maxLength={254}
              placeholder="demo@example.com"
            />
            {error("email")}
          </div>
          {!contact && (
            <>
              <div className="form-field">
                <label htmlFor={fieldId("trade")}>Trade or business type</label>
                <select {...props("trade")} required defaultValue="">
                  <option value="" disabled>
                    Select your trade
                  </option>
                  {[
                    "Electrician",
                    "Plumber",
                    "Builder",
                    "Carpenter",
                    "Painter & decorator",
                    "Landscaper",
                    "Other trade or business",
                  ].map((t) => (
                    <option key={t}>{t}</option>
                  ))}
                </select>
                {error("trade")}
              </div>
              <div className="form-field">
                <label htmlFor={fieldId("phone")}>
                  Phone number <span className="optional">(optional)</span>
                </label>
                <input
                  {...props("phone")}
                  type="tel"
                  autoComplete="off"
                  maxLength={24}
                  placeholder="Leave blank for this demonstration"
                />
                {error("phone")}
              </div>
            </>
          )}
          <div className="form-field">
            <label htmlFor={fieldId("message")}>
              {contact
                ? "Your message"
                : "What admin would you like help with?"}
              {!contact && <span className="optional"> (optional)</span>}
            </label>
            <textarea
              {...props("message")}
              required={contact}
              rows={3}
              maxLength={3000}
              placeholder={
                contact
                  ? "Try a sample enquiry…"
                  : "Invoicing, keeping track of job details…"
              }
            />
            {error("message")}
          </div>
          <div className="consent-control">
            <label className="checkbox" htmlFor={fieldId("consent")}>
              <input {...props("consent")} type="checkbox" required />
              <span>
                {contact
                  ? "I agree to be contacted about this enquiry"
                  : "I agree to be contacted about An Oifig early access"}{" "}
                <span className="optional">
                  (demonstration only; no contact will take place).
                </span>
              </span>
            </label>
            {error("consent")}
          </div>
          <p className="form-privacy">
            Read the <Link href="/privacy">draft privacy notice</Link>. This
            consent control is a preview; real data collection is not enabled.
          </p>
          <button
            className="button"
            disabled={status === "submitting"}
            type="submit"
          >
            {status === "submitting"
              ? "Trying the form…"
              : contact
                ? "Try contact demo"
                : "Try early-access signup"}{" "}
            <ArrowUpRight size={17} />
          </button>
          {status === "error" && (
            <p className="field-error" role="alert">
              The demonstration couldn’t complete. Please try again; nothing was
              sent.
            </p>
          )}
          <div className="form-reassurance">
            <Check size={14} />
            No account. No payment. No real submission.
          </div>
        </form>
      )}
    </div>
  );
}
