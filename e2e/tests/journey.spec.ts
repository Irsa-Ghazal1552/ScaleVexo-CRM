import { expect, test, type Page } from '@playwright/test'
import { dialog, noErrorToast, signIn, USERS } from './helpers'

// The primary Release 1 journey, driven through the UI only:
// import CSV → assign lead → log activity → create deal → move stages → win →
// accept handover → complete milestones → raise and resolve a ticket.
test.describe.configure({ mode: 'serial' })

const run = Date.now().toString(36)
const company = `E2E Dental ${run}`
const contact = `Erin Example ${run}`
const csv = [
  'Name,Company,Email,Phone,Source',
  `${contact},${company},erin.${run}@e2e.test,,Trade show`,
  `Second ${run},E2E Second ${run},second.${run}@e2e.test,,Trade show`,
  `Third ${run},E2E Third ${run},third.${run}@e2e.test,,Trade show`,
].join('\n')

async function pickOption(page: Page, label: string | RegExp, text: string) {
  const select = dialog(page).getByLabel(label)
  const value = await select.locator('option', { hasText: text }).first().getAttribute('value')
  await select.selectOption(value!)
}

async function milestoneRow(page: Page, title: string) {
  return page.locator('.task').filter({ has: page.locator('.ttl', { hasText: title }) })
}

test('sales: import, assign, log activity, create deal, move stages, win', async ({ page }) => {
  await signIn(page, USERS.salesManager)

  // Import CSV
  await page.getByRole('link', { name: 'Leads' }).click()
  await page.getByRole('link', { name: 'Import CSV' }).click()
  await page.locator('input[type=file]').setInputFiles({ name: `e2e-${run}.csv`, mimeType: 'text/csv', buffer: Buffer.from(csv) })
  await page.getByRole('button', { name: 'Import 3 rows' }).click()
  await expect(page.locator('.tile', { hasText: 'created' }).locator('.v')).toHaveText('3')
  await noErrorToast(page)

  // Assign the lead
  await page.getByRole('link', { name: 'Leads' }).click()
  await page.getByPlaceholder(/Search name, company/).fill(company)
  await page.getByText(contact, { exact: true }).click()
  await expect(page.getByRole('heading', { name: contact })).toBeVisible()
  await page.locator('.card').filter({ has: page.getByRole('heading', { name: 'Lead', exact: true }) }).getByRole('button', { name: 'Edit' }).click()
  await pickOption(page, 'Owner', 'Rabia Muneeb')
  await dialog(page).getByRole('button', { name: 'Save' }).click()
  await expect(dialog(page)).toHaveCount(0)
  await expect(page.getByRole('group', { name: 'Stages' }).getByRole('button', { name: 'Assigned' })).toHaveAttribute('aria-current', 'step')

  // Log an activity
  await page.getByLabel('Outcome').fill('Spoke with Erin - wants a booking site')
  await page.getByLabel('Notes').fill('Three clinics, decision this month.')
  await page.locator('.composer').getByRole('button', { name: 'Save' }).click()
  await expect(page.getByText('Spoke with Erin - wants a booking site').first()).toBeVisible()
  await expect(page.getByText(/self-reported/i).first()).toBeVisible()

  // Create a deal
  await page.getByRole('button', { name: 'Create deal' }).click()
  await dialog(page).getByLabel('Deal title').fill(`Booking site ${run}`)
  await dialog(page).getByLabel(/Value/).fill('4800')
  await dialog(page).getByLabel('Need', { exact: true }).fill('Online booking for three clinics')
  await dialog(page).getByLabel('Fit', { exact: true }).fill('We build booking sites')
  await dialog(page).getByRole('button', { name: 'Save' }).click()
  await expect(page).toHaveURL(/\/deals\//)
  await expect(page.getByRole('heading', { name: `Booking site ${run}` })).toBeVisible()

  // Move stages: Proposal needs a scope reference, Negotiation needs nothing more
  const stages = page.getByRole('group', { name: 'Stages' })
  await stages.getByRole('button', { name: 'Proposal' }).click()
  await dialog(page).getByRole('button', { name: 'Move' }).click()
  await expect(dialog(page).getByText('Please fill in the required fields.')).toBeVisible()
  await dialog(page).getByLabel(/Scope \/ proposal reference/).fill(`Proposal P-${run}`)
  await dialog(page).getByRole('button', { name: 'Move' }).click()
  await expect(stages.getByRole('button', { name: 'Proposal' })).toHaveAttribute('aria-current', 'step')
  await stages.getByRole('button', { name: 'Negotiation' }).click()
  await expect(stages.getByRole('button', { name: 'Negotiation' })).toHaveAttribute('aria-current', 'step')

  // Win: needs scope, reference, decision and a delivery owner
  await page.getByRole('button', { name: 'Close as won' }).click()
  await expect(dialog(page).getByText(/Won does not mean paid/)).toBeVisible()
  await dialog(page).getByLabel(/Accepted scope/).fill('Booking site for three clinics, local SEO for 3 months')
  await pickOption(page, /Delivery owner/, 'Hamza Iqbal')
  await dialog(page).getByLabel(/Commercial decision/).fill('CEO approved, 50% advance')
  await dialog(page).getByRole('button', { name: 'Close as won' }).click()
  await expect(dialog(page)).toHaveCount(0)
  await expect(stages.getByRole('button', { name: 'Won' })).toHaveAttribute('aria-current', 'step')
  await noErrorToast(page)
})

test('delivery: accept handover and complete every milestone', async ({ page }) => {
  await signIn(page, USERS.deliveryManager)
  await page.getByRole('link', { name: 'Handovers' }).click()
  const card = page.locator('.card').filter({ has: page.getByRole('heading', { name: company }) })
  await card.getByRole('button', { name: 'Accept handover' }).click()
  await expect(card).toHaveCount(0) // accepted handovers leave the "needs action" list
  await page.getByRole('link', { name: 'Projects' }).click()
  await page.getByText(`Onboarding - ${company}`).click()
  await expect(page.getByRole('heading', { name: `Onboarding - ${company}` })).toBeVisible()
  await expect(page.getByText(/Waiting for the delivery owner to accept/)).toHaveCount(0)

  const titles = await page.locator('.task .ttl').allInnerTexts()
  expect(titles.length).toBeGreaterThan(0)
  for (const title of titles) {
    const row = await milestoneRow(page, title)
    await row.getByRole('button', { name: 'Start' }).click()
    await row.getByRole('button', { name: 'Submit for review' }).click()
    await dialog(page).getByLabel(/Evidence for the reviewer/).fill(`Evidence for ${title}`)
    await dialog(page).getByRole('button', { name: 'Save' }).click()
    await expect(dialog(page)).toHaveCount(0)
    await row.getByRole('button', { name: /^Accept/ }).click()
    await expect(row.getByText('Accepted', { exact: true })).toBeVisible()
  }
  await expect(page.getByText(`Milestones (${titles.length}/${titles.length} accepted)`)).toBeVisible()
  await noErrorToast(page)
})

test('support: raise and resolve a ticket', async ({ page }) => {
  await signIn(page, USERS.deliveryManager)
  await page.getByRole('link', { name: 'Tickets' }).click()
  await page.getByRole('button', { name: 'Ticket' }).click()
  await dialog(page).getByLabel('Title').fill(`Booking emails not sent ${run}`)
  await dialog(page).getByLabel('Severity').selectOption('high')
  await pickOption(page, 'Client', company)
  await pickOption(page, 'Owner', 'Hamza Iqbal')
  await dialog(page).getByRole('button', { name: 'Save' }).click()
  await expect(page).toHaveURL(/\/tickets\//)
  await expect(page.getByRole('heading', { name: new RegExp(`Booking emails not sent ${run}`) })).toBeVisible()

  await page.getByRole('button', { name: 'Start work' }).click()
  await page.getByRole('button', { name: 'Resolve' }).click()
  await dialog(page).getByRole('button', { name: 'Save' }).click()
  await expect(dialog(page).getByText('Please fill in the required fields.')).toBeVisible()
  await dialog(page).getByLabel(/Resolution - what was done/).fill('Fixed the SMTP settings')
  await dialog(page).getByLabel(/Closure test result/).fill('Booked a test slot; confirmation email arrived')
  await dialog(page).getByRole('button', { name: 'Save' }).click()
  await expect(dialog(page)).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Close', exact: true })).toBeVisible()
  await expect(page.getByText('Fixed the SMTP settings', { exact: true })).toBeVisible()
  await noErrorToast(page)
})
