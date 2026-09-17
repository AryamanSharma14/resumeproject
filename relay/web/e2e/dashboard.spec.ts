import { expect, test } from './fixtures';

test('token authenticates in memory and disconnects cleanly', async ({ page }) => {
  await page.goto('/jobs');
  await expect(page.getByRole('heading', { name: 'Connect to your installation.' })).toBeVisible();
  await page.getByLabel('Installation access token').fill(process.env.RELAY_E2E_TOKEN!);
  await page.getByRole('button', { name: 'Connect to Relay' }).click();
  await expect(page.getByRole('heading', { name: 'Jobs' })).toBeVisible();
  await page.getByRole('button', { name: 'Disconnect' }).click();
  await expect(page.getByRole('heading', { name: 'Connect to your installation.' })).toBeVisible();
});

test('submit text_summary and inspect its timeline until terminal', async ({ page }) => {
  await page.goto('/jobs');
  await page.getByLabel('Installation access token').fill(process.env.RELAY_E2E_TOKEN!);
  await page.getByRole('button', { name: 'Connect to Relay' }).click();
  await expect(page.getByRole('heading', { name: 'Jobs' })).toBeVisible();
  await page.getByRole('button', { name: 'Submit job' }).click();
  await expect(page.getByRole('heading', { name: 'Submit job' })).toBeVisible();
  await page.getByLabel('Text').fill('Industrial instrument panel copy for the live check.');
  await page.getByRole('button', { name: 'Submit job' }).click();
  await expect(page.getByRole('heading', { name: 'Job inspection' })).toBeVisible();
  await expect(page.getByText('Attempt 1')).toBeVisible();
  await expect(page.getByText(/succeeded/).first()).toBeVisible();
});
