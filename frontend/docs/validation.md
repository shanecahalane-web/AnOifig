# Validation — 15 October 2026

- Node 24.19.0 / npm 11.9.0; Next.js 16.4.1 installed from package-lock.json.
- `npm ci --cache /workspace/.npm-cache --no-audit --no-fund`: passed; repeated frozen installation.
- `npm run build`: passed; all five public routes statically prerendered.
- `npm run typecheck`: passed.
- `npm run format:check`: passed.
- `npm audit --omit=dev --audit-level=high --cache /workspace/.npm-cache`: passed; zero reported production vulnerabilities.
- `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npm test`: **14 passed** across desktop Chromium and mobile Chromium with iPhone 13 viewport/touch emulation. This is not real iOS Safari validation.
- Automated axe WCAG 2 A/AA and 2.1 AA scans: no violations on homepage, early-access, contact, privacy and terms at both tested viewports. Automated checks do not replace manual assistive-technology testing.
- Functional tests verify draft-before-approval order, complete simulation, restart, mobile navigation, all public pages, FAQ expansion, truthful pricing/legal labels, form validation/local downloads, no POST on interest draft, overflow and browser errors.
- Desktop and mobile screenshots were generated from the tested production server and visually reviewed. See `screenshots/`.

The initial FAQ test used an exact text locator that included a decorative plus in the rendered text; the locator was corrected to target the summary. The initial accessibility scan found low-contrast secondary text; palette values were corrected and the complete suite rerun successfully.

Backend files are unchanged. Backend/database suites were not run for this isolated frontend addition. No real external services, production deployment, invoice issuance or payments were tested or connected.

The reference site returned HTTP 403 in this environment; no claim is made that its presentation was inspected. The original design follows the requested product narrative and brand direction.
