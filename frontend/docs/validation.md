# Phase 2 validation — 15 October 2026

- Node 24.19.0 / npm 11.9.0; Next.js 16.4.1 using the existing package-lock.json. No new dependencies.
- `npm run build`: passed; all five public pages statically prerendered.
- `npm run typecheck`: passed.
- `npm run format:check`: passed.
- `npm audit --omit=dev --audit-level=high --cache /workspace/.npm-cache`: passed; zero reported production vulnerabilities.
- `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npm test`: **35 passed** (5 pure unit tests, 30 browser tests). No skipped or expected-failure tests.
- Browser projects: desktop Chromium, iPhone 13 viewport/touch emulation, and 320 × 740 Android-sized Chromium. These are emulations, not real-device Safari/Android validation.
- Additional responsive checks: 320, 360, 390, 768, 1440 and 1920px widths. No horizontal overflow. The demo start button is visible in the tested 1280 × 720 desktop viewport.
- Automated axe WCAG 2 A/AA and 2.1 AA scans: no violations across homepage, early-access, contact, privacy, terms and the invoice dialog at all three project sizes. Automated scans are not a complete assistive-technology audit.
- Lifecycle coverage: request, typing, review, correction, revision invalidation, explicit current-version approval, PDF download and reset. Tests reject unreviewed/stale approvals and invalid/repeated corrections; restarting during typing cancels the pending reply.
- Calculation checks: integer-cent parsing, boundaries, half-up VAT rounding and €450 → €500 before illustrative VAT. The revised sample is €500 + €67.50 = €567.50 at the assumed 13.5% rate.
- Sample PDF: current revision/amounts, valid PDF object offsets, fictional labels, no obsolete amount. Independent `pdfinfo` and `pdftotext` inspection confirmed a one-page A4 PDF 1.4, extractable correct totals, no PDF JavaScript, and clear sample/not-payable notices. The sample PDF is not a tagged accessible PDF; the corresponding HTML document uses semantic headings, table headers and description lists.
- Mock signup/contact: client validation, associated errors, focus on invalid input, explicit consent, sample-fill control, truthful confirmation and cleared values. Assertions verify no POST request or local/session storage. The adapter itself contains no network, log or persistence operations.
- Navigation, Escape behaviour, restored dialog focus, reduced motion, browser console/page errors, roadmap/legal labels and sample-only delivery messaging are covered. Tests start a fresh production server on dedicated port 3100, avoiding stale static-asset references from a preview process that predates a build.
- Desktop/mobile captures were generated from the tested production server and visually inspected. See `screenshots/` and the sample PDF in this directory. The screenshot gallery explains the captured states.

Only `frontend/` changed. Backend code, dependencies, migrations, authentication and Twilio integration are unchanged. Backend/database tests were not run for this frontend-only change. No live integrations, customer data collection, invoice issuance, paid resources or public deployment were used.

Outstanding: approved real signup/contact destination and operator details, reviewed privacy/retention/security controls, legal review and official logo asset. The current mock intentionally remains usable without them. Reference-site inspection and PR creation are separately blocked by the environment's enforced domain policy (HTTP 403). Required domains exist in the saved draft but are not applied to the running machine.
