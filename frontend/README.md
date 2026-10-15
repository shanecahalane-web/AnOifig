# An Oifig public website

A standalone Next.js App Router / TypeScript / Tailwind marketing site. All implementation stays inside `frontend/`; it does not use the Python backend, database, authentication, Twilio or OpenAI. Continue on `feat/public-marketing-website` using the existing isolated checkout, without a Git worktree. Do not merge or deploy automatically.

## Run and review interactively

Node 24 and npm 11 are the validated toolchain. From this cloud checkout:

```sh
cd /workspace/AnOifig/frontend
npm ci --cache /workspace/.npm-cache
npm run dev
```

The development server listens on port 3000. On your own machine, open that port in your browser to interact with Tara. This cloud onboarding UI does not expose a user-facing localhost preview; use the committed screenshots, or run the branch locally. No environment variables or paid integrations are required.

For a production-mode local preview:

```sh
npm run build
npm run start
```

## Check the implementation

```sh
npm run typecheck
npm run format:check
npm run build
# Normal developer machine: install the matching Playwright browser once.
npx playwright install chromium
npm test
# This cloud machine already has Chromium; no browser download is necessary.
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npm test
npm audit --omit=dev --audit-level=high --cache /workspace/.npm-cache
```

The existing Playwright infrastructure runs pure unit checks plus desktop, iPhone 13 and 320px Android-sized Chromium browser projects. Tests start a fresh production server on dedicated port 3100 (build first) and never reuse an existing process. Stop/restart your own production preview after rebuilding; an old process can refer to removed static assets. They cover the invoice lifecycle and corrections, approval of the exact reviewed revision, deterministic VAT rounding, PDF structure/content, form validation and consent, absence of submissions/browser storage, reset during typing, dialog keyboard/focus behaviour, navigation, overflow, reduced motion, console errors and automated axe scans. Test screenshots and sample PDFs are written under ignored `test-results/`. See `docs/validation.md` for results and scope limits.

## Try Tara

1. Select **Send invoice request** in the homepage hero. All customer/job data is fixed and fictional.
2. **Review invoice draft** opens an accessible document dialog: customer, dates, item, subtotal, illustrative VAT and payment details.
3. Select **Change amount** and enter `500`, or close the preview and use the guided €500 correction.
4. Review the new version: €500.00 + €67.50 assumed VAT = €567.50. Editing invalidates the previous review; the updated version must be opened before approval.
5. Explicitly approve the current version, then download the real, clearly marked **sample PDF**. Nothing is issued, sent or payable.
6. **Restart** clears the conversation, including pending typing replies. Escape closes the invoice dialog and returns focus to its opener.

The rate is a fixed **13.5% demonstration assumption**, not a claim about the correct Irish VAT treatment for any actual job. Calculations use integer cents and half-up rounding; no floating-point money is stored in the workflow. Dates are fixed to 15/29 October 2026 for repeatable results. The revision check protects this local simulation, not a future server-side approval system.

## Components and integration boundaries

- `components/demo.tsx`: the interactive WhatsApp-inspired conversation, typing indicator, controls, dialog and reset.
- `components/invoice-preview.tsx`: accessible sample invoice document.
- `lib/tara-demo.ts`: deterministic lifecycle reducer, revision guards, parsing and currency calculations.
- `lib/invoice-pdf.ts`: lightweight one-page A4 sample PDF generation; no added dependency or external service.
- `components/enquiry-form.tsx`: signup/contact mock with validation, inline errors, sample-fill control and explicit consent.
- `lib/enquiry.ts`: typed future submission boundary. The current adapter performs no network requests, logs, downloads or storage and explicitly returns `persisted: false`.
- `lib/site-config.ts`: editable early-access invitation and unconfirmed pricing copy.
- `app/page.tsx`: retained homepage sections with clearer positioning, correction illustration, sample PDF feature and six distinctly planned roadmap items.
- `components/shell.tsx`: shared header/footer and mobile navigation. **Official logo insertion points are the two `.brand` links here.** No official asset is in the repository; the existing text branding is retained. Add an approved favicon in `app/layout.tsx` too; its current empty icon prevents a missing-favicon request without inventing a brand asset.
- `app/globals.css`: the existing forest green / gold / cream identity, responsive product styles, readable invoice layout and reduced-motion support.
- `docs/screenshots/`: actual reviewed application captures, not fabricated product imagery.

## Demonstration mode and release prerequisites

**Do not enter real personal or customer information.** Signup and contact forms now simulate a submission instead of downloading personal details. A sample-fill button supplies fictional information. A successful mock clears the fields and states that no waiting-list entry or message was created. Data lives only in current-page memory for validation; nothing is transmitted or persisted. Do not change this into real data collection until a secure approved destination, reviewed privacy notice, retention/deletion policy, consent process and security controls exist. A real service also needs server-side validation and spam/rate protection; client validation is not a security boundary.

A future adapter must use an explicitly designed live result type and live UI; it must not return the demo result or reuse demo confirmations to imply successful registration. No API URL, credentials, third-party forms service or unreviewed endpoint has been invented.

Pricing is not approved. The site invites visitors to explore early access rather than publishing subscription amounts. Voice notes, quotations, reminders, expense tracking, job management and customer follow-ups are **planned**, not available features. No testimonials, counts, ratings or certifications are fabricated.

Privacy and Terms are marked drafts and excluded from indexing. Legal review, verified operator/contact details and hosting/privacy assessment remain required before publication. No analytics or external font downloads are connected. Set the approved domain and social sharing assets before adding domain-specific canonical/sitemap URLs.

The requested reference `https://manano.ai` remains blocked by the environment's network policy (HTTP 403); its current presentation could not be inspected. No proprietary reference code, text, images or exact layouts were copied. The saved environment draft already requests `manano.ai`, `www.manano.ai` and `api.github.com`; applying those settings is needed for reference review and PR API access. A saved draft alone does not change runtime policy.
