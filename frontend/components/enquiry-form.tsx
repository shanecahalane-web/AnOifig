"use client";
import { useState, type FormEvent } from "react";
import { Download } from "lucide-react";
export default function EnquiryForm({
  contact = false,
}: {
  contact?: boolean;
}) {
  const [done, setDone] = useState(false);
  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const url = URL.createObjectURL(
      new Blob(
        [
          "An Oifig — local enquiry draft only\n" +
            Array.from(data.entries())
              .map(([k, v]) => `${k}: ${v}`)
              .join("\n"),
        ],
        { type: "text/plain" },
      ),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "an-oifig-enquiry.txt";
    a.click();
    URL.revokeObjectURL(url);
    setDone(true);
  }
  return (
    <form className="enquiry-form" onSubmit={submit}>
      <div className="form-notice">
        <strong>Preview — no submission service connected.</strong>
        <p>
          Details stay in this browser. Download a local draft; this does not
          register you or send a message. Please don’t include sensitive
          information.
        </p>
      </div>
      <label>
        Your name
        <input
          name="Name"
          required
          autoComplete="name"
          maxLength={120}
          placeholder="e.g. Cian Murphy"
        />
      </label>
      <label>
        Email address
        <input
          name="Email"
          type="email"
          required
          autoComplete="email"
          maxLength={254}
          placeholder="you@yourbusiness.ie"
        />
      </label>
      {!contact && (
        <label>
          Your trade
          <select name="Trade" required defaultValue="">
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
              "Other",
            ].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
      )}
      <label>
        {contact
          ? "Your message"
          : "What admin would you like help with? (optional)"}
        <textarea name="Message" required={contact} rows={4} maxLength={3000} />
      </label>
      <label className="checkbox">
        <input type="checkbox" required />
        <span>
          I understand this creates a local draft only and does not submit my
          information.
        </span>
      </label>
      <button className="button" type="submit">
        Download {contact ? "enquiry" : "early-access"} draft{" "}
        <Download size={17} />
      </button>
      {done && (
        <p role="status">
          Your draft is ready to save. Nothing has been sent. You have not been
          added to a waiting list.
        </p>
      )}
    </form>
  );
}
