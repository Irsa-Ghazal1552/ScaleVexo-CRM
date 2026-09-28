import { expect, type Page } from '@playwright/test'

export const DEMO_PASSWORD = 'DemoPass!2026'
export const USERS = {
  owner: { email: process.env.E2E_OWNER_EMAIL || 'ceo@scalevexo.com', password: process.env.E2E_OWNER_PASSWORD || '' },
  salesManager: { email: 'sara@demo.scalevexo.local', password: DEMO_PASSWORD },
  salesRep: { email: 'rabia@demo.scalevexo.local', password: DEMO_PASSWORD },
  deliveryManager: { email: 'hamza@demo.scalevexo.local', password: DEMO_PASSWORD },
}

export async function signIn(page: Page, user: { email: string; password: string }) {
  await page.context().clearCookies()
  await page.goto('/login')
  await page.getByLabel('Work email').fill(user.email)
  await page.getByLabel('Password').fill(user.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).not.toHaveURL(/\/login/)
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
}

/** The open dialog (the app shows one at a time). */
export const dialog = (page: Page) => page.getByRole('dialog')

/** Fails the test if the page shows an error toast. */
export async function noErrorToast(page: Page) {
  await expect(page.locator('.toast.error')).toHaveCount(0)
}
