import { test, expect } from "@playwright/test";
test("invoice demonstration requires all steps and can restart", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Your office,in your pocket.",
  );
  await expect(page.getByText("Approval recorded · demo only")).toHaveCount(0);
  await page.getByRole("button", { name: "Ask for an invoice" }).click();
  await expect(
    page.getByText("What work should I include", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Add the details" }).click();
  await expect(page.getByText("DEMO-001 · For review")).toBeVisible();
  await expect(page.getByText("Approval recorded · demo only")).toHaveCount(0);
  await page.getByRole("button", { name: "Approve the draft" }).click();
  await expect(page.getByText("Approval recorded · demo only")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Demo complete" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Restart demonstration" }).click();
  await expect(
    page.getByRole("button", { name: "Ask for an invoice" }),
  ).toBeEnabled();
  await expect(page.getByText("DEMO-001 · For review")).toHaveCount(0);
});
test("navigation and pages are accessible on the selected viewport", async ({
  page,
  isMobile,
}) => {
  await page.goto("/");
  if (isMobile) {
    await page.getByRole("button", { name: "Open navigation" }).click();
    await expect(
      page.getByRole("button", { name: "Close navigation" }),
    ).toHaveAttribute("aria-expanded", "true");
  }
  await page
    .getByRole("navigation")
    .getByRole("link", { name: "Contact", exact: true })
    .click();
  await expect(page).toHaveURL(/contact/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Good ideas",
  );
  for (const path of ["/early-access", "/privacy", "/terms"]) {
    await page.goto(path);
    await expect(page.locator("main h1")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
  }
});
test("early access downloads a local draft without claiming registration", async ({
  page,
}) => {
  await page.goto("/early-access");
  await page.getByLabel("Your name").fill("Demo Tradesperson");
  await page.getByLabel("Email address").fill("demo@example.com");
  await page.getByLabel("Your trade").selectOption("Electrician");
  await page.getByRole("checkbox").check();
  const requestMethods: string[] = [];
  page.on("request", (r) => requestMethods.push(r.method()));
  const download = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download early-access draft" })
    .click();
  expect((await download).suggestedFilename()).toBe("an-oifig-enquiry.txt");
  await expect(page.getByRole("status")).toContainText("Nothing has been sent");
  expect(requestMethods).not.toContain("POST");
});
test("FAQ, pricing and legal drafts accurately describe the preview", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .locator("summary")
    .filter({ hasText: "Is Tara available to use today?" })
    .click();
  await expect(
    page.getByText("Not yet. This website demonstrates", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Pricing to be confirmed" }),
  ).toBeVisible();
  await page.goto("/privacy");
  await expect(
    page.getByText("DRAFT — REQUIRES LEGAL REVIEW.", { exact: false }),
  ).toBeVisible();
  await page.goto("/terms");
  await expect(
    page.getByText("DRAFT — REQUIRES LEGAL REVIEW.", { exact: false }),
  ).toBeVisible();
});
test("homepage has no overflow or browser errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  expect(errors).toEqual([]);
  await page.screenshot({
    path: `test-results/home-${test.info().project.name}.png`,
    fullPage: true,
  });
});

test("public pages pass automated WCAG accessibility checks", async ({
  page,
}) => {
  const { default: AxeBuilder } = await import("@axe-core/playwright");
  for (const path of ["/", "/early-access", "/contact", "/privacy", "/terms"]) {
    await page.goto(path);
    const result = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    expect(
      result.violations.map((v) => ({
        id: v.id,
        nodes: v.nodes.map((n) => n.target),
      })),
    ).toEqual([]);
  }
});

test("contact form validates required fields before creating a local draft", async ({
  page,
}) => {
  await page.goto("/contact");
  await page.getByRole("button", { name: "Download enquiry draft" }).click();
  await expect(page.getByRole("status")).toHaveCount(0);
  await page.getByLabel("Your name").fill("Demo Person");
  await page.getByLabel("Email address").fill("demo@example.com");
  await page
    .getByLabel("Your message")
    .fill("A fictional enquiry for testing.");
  await page.getByRole("checkbox").check();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download enquiry draft" }).click();
  expect((await download).suggestedFilename()).toBe("an-oifig-enquiry.txt");
  await expect(page.getByRole("status")).toContainText("Nothing has been sent");
});
