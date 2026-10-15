/** Integration boundary. Replace only after an approved secure destination and policies exist. */
export type Enquiry = {
  name: string;
  email: string;
  trade?: string;
  phone?: string;
  message?: string;
  consent: boolean;
};
export type EnquiryErrors = Partial<Record<keyof Enquiry, string>>;
export function validateEnquiry(
  value: Enquiry,
  contact = false,
): EnquiryErrors {
  const errors: EnquiryErrors = {};
  if (value.name.trim().length < 2 || value.name.length > 120)
    errors.name = "Enter a name between 2 and 120 characters.";
  if (value.email.length > 254 || !/^\S+@[^\s@]+\.[^\s@]+$/.test(value.email))
    errors.email = "Enter an email address, such as demo@example.com.";
  if (!contact && !value.trade)
    errors.trade = "Choose a trade or business type.";
  if (
    value.phone &&
    (!/^[+\d\s().-]{7,24}$/.test(value.phone) ||
      value.phone.replace(/\D/g, "").length < 7)
  )
    errors.phone =
      "Enter a phone number with at least seven digits, or leave this blank.";
  if (contact && !value.message?.trim())
    errors.message = "Write a short message for this demonstration.";
  if (value.message && value.message.length > 3000)
    errors.message = "Keep your message under 3,000 characters.";
  if (!value.consent)
    errors.consent = contact
      ? "Confirm the contact consent to try the demonstration."
      : "Confirm the early-access contact consent to try the demonstration.";
  return errors;
}
export type EnquiryResult = { mode: "demo"; persisted: false };
export async function submitDemoEnquiry(
  _enquiry: Enquiry,
): Promise<EnquiryResult> {
  // Intentionally no fetch, logs, cookies, downloads or browser storage.
  return { mode: "demo", persisted: false };
}
