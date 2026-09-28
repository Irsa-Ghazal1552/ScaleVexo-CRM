import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { signIn, USERS } from './helpers'

// WCAG 2.1 A/AA checks on the core screens.
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

async function check(page: Page, name: string) {
  await page.waitForLoadState('networkidle')
  const { violations } = await new AxeBuilder({ page }).withTags(TAGS).analyze()
  const summary = violations.map((v) => `${v.id} (${v.impact}): ${v.help} → ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`)
  expect(summary, `${name} accessibility violations`).toEqual([])
}

test('login screen', async ({ page }) => {
  await page.goto('/login')
  await check(page, 'login')
})

test.describe('signed in', () => {
  const screens = ['/', '/leads', '/deals', '/deals?view=list', '/clients', '/handovers', '/projects', '/tickets', '/team', '/reports', '/alerts', '/settings']

  for (const path of screens) {
    test(`screen ${path}`, async ({ page }) => {
      await signIn(page, USERS.owner)
      await page.goto(path)
      await check(page, path)
    })
  }

  test('detail pages', async ({ page }) => {
    await signIn(page, USERS.owner)
    for (const [list, prefix] of [['/leads', '/leads/'], ['/deals?view=list', '/deals/'], ['/projects', '/projects/'], ['/tickets', '/tickets/']]) {
      await page.goto(list)
      const link = page.locator(`a[href^="${prefix}"]`).first()
      if (await link.count()) {
        await link.click()
        await check(page, `${prefix}…`)
      }
    }
  })
})
