import { expect, test } from "@playwright/test";

test("learning activity filter preserves other filters and can be removed", async ({
  page,
}) => {
  await page.goto("/search?subject=COMPSCI&availability=all");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await page
    .getByRole("button", { name: "Learning activity", exact: true })
    .click();
  await page.getByRole("option", { name: "Programming", exact: true }).click();
  await expect(page).toHaveURL(/activity=programming/);
  const selected = new URL(page.url());
  expect(selected.searchParams.get("subject")).toBe("COMPSCI");
  expect(selected.searchParams.get("availability")).toBe("all");
  const chip = page.getByRole("button", {
    name: "Remove Learning activity: Programming",
    exact: true,
  });
  await expect(chip).toHaveText("Learning activity: Programming");
  await expect(chip).toBeVisible();
  await chip.click();
  await expect(page).not.toHaveURL(/activity=/);
  expect(new URL(page.url()).searchParams.get("subject")).toBe("COMPSCI");
  await expect(page.locator(".discovery-card").first()).toBeVisible();
});
