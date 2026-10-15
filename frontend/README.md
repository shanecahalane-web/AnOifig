# An Oifig public website

A standalone Next.js App Router / TypeScript / Tailwind marketing site. It has no dependency on the Python backend, PostgreSQL, Twilio, OpenAI, or a customer dashboard. All implementation is under `frontend/`.

## Develop

Use Node.js 24 (validated with 24.19.0) and npm 11.

```sh
cd /workspace/AnOifig/frontend
npm ci --cache /workspace/.npm-cache
npm run dev
```

The dev server uses port 3000. For production-mode local validation:

```sh
npm run build
npm run start
```

No environment variables, paid integrations or credentials are required. Use the existing isolated checkout; do not create a Git worktree. The implementation branch is `feat/public-marketing-website`. Do not merge or deploy automatically.

## Checks

```sh
npm run typecheck
npm run format:check
npm run build
# Use a browser installed by Playwright on normal developer machines:
npx playwright install chromium
npm test
# This cloud environment already has Chromium; no browser download is necessary:
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npm test
npm audit --omit=dev --audit-level=high --cache /workspace/.npm-cache
```

Playwright starts the production server automatically (build first). It checks desktop and mobile layouts, navigation, the entire demo and explicit approval order, reset, form validation/downloads, FAQ, legal labels, page errors, overflow and automated WCAG checks. Tests write screenshots under ignored `test-results/`. Browsers are not retained processes; start the site again in a new cloud task.

## Structure and content

- `app/page.tsx`: homepage, how it works, features, roadmap, pricing and FAQ.
- `components/demo.tsx`: a three-step fictional WhatsApp-style invoice conversation. State is in memory and resets on reload. No external requests, invoice issuance or messages.
- `app/early-access/`, `app/contact/`: accessible, validated local enquiry-draft forms.
- `app/privacy/`, `app/terms/`: explicitly unfinished legal drafts, excluded from indexing.
- `lib/site-config.ts`: configurable placeholder pricing text. Prices remain unconfirmed; do not publish speculative amounts as confirmed plans.
- `app/globals.css`: forest green / muted gold styling, responsive layouts and reduced-motion support. System fonts avoid font downloads.
- `docs/screenshots/`: reviewed desktop/mobile captures.

## Publication prerequisites

This is a functional marketing preview, not a launched signup service. Form entries are **not transmitted or stored**: the user downloads a local text file. The UI states this before input and never claims a successful signup. Connecting actual registration and contact delivery requires a separately selected destination, spam/rate controls, secure handling, retention/deletion rules, reviewed privacy information and an approved contact address. No address was invented.

No official logo exists in the inspected repository. Navigation uses the business name as plain text. Replace it with the official asset only when supplied; no substitute logo has been generated.

The invoice workflow and all amounts/customer names are fictional. The demo does not assess VAT, generate a legally valid invoice, or issue/send documents. Planned features are marked as such. No testimonials, statistics or ratings are fabricated.

Privacy and Terms require Irish legal review, complete operator/contact details and hosting/privacy assessment before release. No analytics are connected. Confirm production domain and social sharing assets before adding canonical URLs, sitemap or domain-specific Open Graph URLs.

The reference `https://manano.ai` could not be inspected: the environment returned HTTP 403. The design is original and does not claim to reproduce or audit that site. No proprietary reference assets or copy were used.

No changes to backend source, migrations, security rules or dependencies are required.
