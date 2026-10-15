import { test, expect, type Page } from "@playwright/test";
async function requestDraft(page: Page) {
  await page.getByRole("button", { name: "Send invoice request" }).click();
  await expect(
    page.getByRole("button", { name: "Review invoice draft" }),
  ).toBeVisible();
}
async function reviewDraft(page: Page) {
  await page.getByRole("button", { name: "Review invoice draft" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
}

test("Tara supports corrections, current-version approval and a genuine sample PDF", async ({
  page,
}) => {
  const errors: string[] = [];
  const posts: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    if (r.method() === "POST") posts.push(r.url());
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Your office,in your pocket.",
  );
  await expect(page.getByRole("button", { name: /Approve v/ })).toHaveCount(0);
  await requestDraft(page);
  await reviewDraft(page);
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Sample invoice version 1")).toContainText(
    "€450.00",
  );
  await expect(dialog.getByLabel("Sample invoice version 1")).toContainText(
    "€510.75",
  );
  await dialog
    .getByRole("button", { name: "Change amount", exact: true })
    .click();
  await page.getByLabel("Amount before VAT (€)").fill("500");
  await page.getByRole("button", { name: "Update draft", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(
    page.getByRole("button", { name: "Review invoice draft" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /Approve v/ })).toHaveCount(0);
  await reviewDraft(page);
  await expect(dialog.getByLabel("Sample invoice version 2")).toContainText(
    "€500.00",
  );
  await expect(dialog.getByLabel("Sample invoice version 2")).toContainText(
    "€67.50",
  );
  await expect(dialog.getByLabel("Sample invoice version 2")).toContainText(
    "€567.50",
  );
  await expect(dialog.getByLabel("Sample invoice version 2")).not.toContainText(
    "€450.00",
  );
  await dialog.screenshot({
    path: `test-results/invoice-${test.info().project.name}.png`,
  });
  await dialog.getByRole("button", { name: "Approve v2 · €567.50" }).click();
  await expect(
    page.getByText("You approved v2. No delivery took place."),
  ).toBeVisible();
  const downloadEvent = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download sample PDF", exact: true })
    .click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe("an-oifig-SAMPLE-v2.pdf");
  await download.saveAs(
    `test-results/sample-approved-${test.info().project.name}.pdf`,
  );
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
  const pdf = Buffer.concat(chunks).toString();
  expect(pdf).toContain("%PDF-1.4");
  expect(pdf).toContain("EUR 567.50");
  expect(pdf).toContain("SAMPLE ONLY");
  await page
    .locator(".tara-demo")
    .screenshot({ path: `test-results/tara-${test.info().project.name}.png` });
  expect(posts).toEqual([]);
  expect(errors).toEqual([]);
  await page.getByRole("button", { name: "Restart demonstration" }).click();
  await expect(
    page.getByRole("button", { name: "Send invoice request" }),
  ).toBeVisible();
  await expect(
    page.getByText("You approved v2. No delivery took place."),
  ).toHaveCount(0);
});

test("custom correction validates input and modal supports Escape and keyboard focus", async ({
  page,
}) => {
  await page.goto("/");
  await requestDraft(page);
  const review = page.getByRole("button", { name: "Review invoice draft" });
  await review.click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(
    page.getByRole("button", { name: "Review current draft" }),
  ).toBeFocused();
  await page.getByRole("button", { name: "Review current draft" }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("button", { name: "Change amount", exact: true })
    .click();
  await page.getByLabel("Amount before VAT (€)").fill("0");
  await page.getByRole("button", { name: "Update draft", exact: true }).click();
  await expect(page.locator("#amount-error")).toContainText("Enter an amount");
  await page.getByLabel("Amount before VAT (€)").fill("500.01");
  await page.getByRole("button", { name: "Update draft", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Review invoice draft" }),
  ).toBeVisible();
  await reviewDraft(page);
  await expect(dialog.getByLabel("Sample invoice version 2")).toContainText(
    "€567.51",
  );
  await dialog.getByRole("button", { name: "Close invoice preview" }).click();
  await page.getByRole("button", { name: "Restart demonstration" }).click();
  await expect(
    page.getByRole("button", { name: "Send invoice request" }),
  ).toBeVisible();
});

test("restarting during typing cancels the pending conversation", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Send invoice request" }).click();
  await page.getByRole("button", { name: "Restart demonstration" }).click();
  await page.waitForTimeout(850);
  await expect(
    page.getByRole("button", { name: "Send invoice request" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Review invoice draft" }),
  ).toHaveCount(0);
});

test("all navigation destinations work and mobile menu handles Escape", async ({
  page,
  isMobile,
}) => {
  await page.goto("/");
  if (isMobile) {
    await page.getByRole("button", { name: "Open navigation" }).click();
    await page.keyboard.press("Escape");
    await expect(
      page.getByRole("button", { name: "Open navigation" }),
    ).toHaveAttribute("aria-expanded", "false");
    await page.getByRole("button", { name: "Open navigation" }).click();
  }
  await page
    .getByRole("navigation")
    .getByRole("link", { name: "Contact", exact: true })
    .click();
  await expect(page).toHaveURL(/contact/);
  for (const path of ["/early-access", "/contact", "/privacy", "/terms", "/"]) {
    const response = await page.goto(path);
    expect(response?.status()).toBe(200);
    await expect(page.locator("main h1")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  }
  const links = await page
    .locator('a[href^="/"]')
    .evaluateAll((links) =>
      Array.from(
        new Set(links.map((l) => l.getAttribute("href")!.split("#")[0])),
      ),
    );
  for (const href of links) {
    expect((await page.request.get(href || "/")).status()).toBe(200);
  }
  for (const hash of ["#demo", "#how-it-works", "#features", "#pricing"])
    await expect(page.locator(hash)).toHaveCount(1);
});

test("mock early access validates fields and consent without sending or persisting data", async ({
  page,
}) => {
  await page.goto("/early-access");
  await page.screenshot({
    path: `test-results/signup-${test.info().project.name}.png`,
    fullPage: true,
  });
  const posts: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST") posts.push(r.url());
  });
  await page
    .getByRole("button", { name: "Try early-access signup", exact: true })
    .click();
  await expect(page.locator(".error-summary")).toContainText(
    "highlighted fields",
  );
  await expect(page.getByLabel("Name", { exact: true })).toBeFocused();
  await page.getByRole("button", { name: "Use sample details" }).click();
  await page.getByLabel("Email address").fill("not-an-email");
  await page
    .getByRole("button", { name: "Try early-access signup", exact: true })
    .click();
  await expect(
    page.getByText("Enter an email address, such as demo@example.com."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Use sample details" }).click();
  await page
    .getByRole("button", { name: "Try early-access signup", exact: true })
    .click();
  await expect(
    page.getByText(
      "Confirm the early-access contact consent to try the demonstration.",
    ),
  ).toBeVisible();
  await page.getByRole("checkbox").check();
  await page
    .getByRole("button", { name: "Try early-access signup", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText(
    "You have not joined a waiting list.",
  );
  await expect(page.getByRole("status")).toContainText(
    "No information was stored.",
  );
  expect(posts).toEqual([]);
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
  expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual([]);
  await page.getByRole("button", { name: "Try the form again" }).click();
  await expect(page.getByLabel("Name", { exact: true })).toHaveValue("");
});

test("contact mock does not claim a real message was sent", async ({
  page,
}) => {
  await page.goto("/contact");
  await page.getByRole("button", { name: "Try contact demo" }).click();
  await expect(
    page.getByText("Write a short message for this demonstration."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Use sample details" }).click();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Try contact demo" }).click();
  await expect(page.getByRole("status")).toContainText(
    "No message has been sent.",
  );
});

test("FAQ, future features and legal drafts accurately describe the preview", async ({
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
    page.getByRole("heading", { name: "Early access, at your pace" }),
  ).toBeVisible();
  for (const feature of [
    "Voice notes",
    "Quotations",
    "Payment reminders",
    "Expense tracking",
    "Job management",
    "Customer follow-ups",
  ])
    await expect(
      page.locator(".coming").getByText(feature, { exact: true }),
    ).toBeVisible();
  for (const path of ["/privacy", "/terms"]) {
    await page.goto(path);
    await expect(
      page.getByText("DRAFT — REQUIRES LEGAL REVIEW.", { exact: false }),
    ).toBeVisible();
    await expect(page.locator("main")).not.toContainText(
      "Forms download a local file",
    );
  }
});

test("public pages and invoice dialog pass automated WCAG checks", async ({
  page,
}) => {
  test.setTimeout(60000);
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
  await page.goto("/");
  await requestDraft(page);
  await reviewDraft(page);
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    result.violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => n.target),
    })),
  ).toEqual([]);
});

test("responsive screens have no overflow and reduced motion is respected", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  for (const width of [320, 360, 390, 768, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  }
  expect(
    await page.evaluate(
      () => getComputedStyle(document.documentElement).scrollBehavior,
    ),
  ).toBe("auto");
});

test("capture reviewed homepage screens without console errors", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.goto("/");
  await page.screenshot({
    path: `test-results/home-${test.info().project.name}.png`,
    fullPage: true,
  });
  if (test.info().project.name === "desktop") {
    const bounds = await page
      .getByRole("button", { name: "Send invoice request" })
      .boundingBox();
    expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(
      page.viewportSize()!.height,
    );
  }
  await page.screenshot({
    path: `test-results/hero-${test.info().project.name}.png`,
  });
  expect(errors).toEqual([]);
});
