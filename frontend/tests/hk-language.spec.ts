import { test, expect } from '@playwright/test'

// Run against a server started with REGION=hk (default http://127.0.0.1:5173).
const HK = process.env.HK_URL || 'http://127.0.0.1:5173'

test('interface language switch keeps data verbatim', async ({ page }) => {
  const posts: string[] = []
  page.on('request', r => { if (r.method() === 'POST' && r.url().includes('/api/workflow')) posts.push(r.postData() || '') })
  await page.goto(HK)
  await expect(page.getByRole('heading', { name: '导入你的租约' })).toBeVisible()
  await page.screenshot({ path: '../work/lang-zh-hans.png' })

  // 繁體: interface converted, report language follows, pasted text untouched
  await page.getByRole('button', { name: '繁體' }).click()
  await expect(page.getByRole('heading', { name: '導入你的租約' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '遇到租房問題，可以找誰' })).toBeVisible()
  await expect(page.getByLabel('報告語言')).toHaveValue('繁體中文')
  await page.screenshot({ path: '../work/lang-zh-hant.png' })
  await page.locator('#contract').fill('第一条 按金港币1000元，退租后7日内退还。')
  await page.getByRole('button', { name: '提取並核對正文' }).click()
  await expect(page.locator('.edit-block textarea').first()).toHaveValue('第一条 按金港币1000元，退租后7日内退还。')

  // ENG: main interface in English, option values unchanged so the backend accepts them
  await page.getByRole('button', { name: 'ENG' }).click()
  await expect(page.getByRole('heading', { name: 'Check first, then analyse' })).toBeVisible()
  await page.getByRole('checkbox', { name: 'I have checked the text and amounts and understand the scope above.' }).check()
  await page.getByRole('combobox', { name: 'Mode', exact: true }).selectOption('demo')
  await page.getByRole('button', { name: 'View demo report' }).click()
  await expect(page.getByText('Demo report · lease not analysed')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'What the lease says' })).toBeVisible()
  await expect(page.locator('.source-panel')).toContainText('第一条 按金港币1000元')
  const body = JSON.parse(posts.at(-1)!)
  expect(body.context.role).toBe('租客')
  expect(body.context.signed).toBe('未知')
  expect(body.context.output_language).toBe('English')
  await page.screenshot({ path: '../work/lang-en-report.png', fullPage: true })

  // Choice persists across reloads
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Import your lease' })).toBeVisible()
  await page.getByRole('button', { name: 'Legislation' }).click()
  await expect(page.getByRole('button', { name: 'Show Chinese text' })).toBeVisible()
  await page.screenshot({ path: '../work/lang-en-home.png' })
  await page.getByRole('button', { name: '简体' }).click()
  await expect(page.getByRole('heading', { name: '导入你的租约' })).toBeVisible()
})

test('language switch fits a phone screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(HK)
  await page.getByRole('button', { name: 'ENG' }).click()
  await expect(page.getByRole('heading', { name: 'Import your lease' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await expect(page.getByRole('button', { name: 'ENG' })).toHaveAttribute('aria-pressed', 'true')
  await page.waitForTimeout(400)  // let the button colour transition finish before the screenshot
  await page.screenshot({ path: '../work/lang-en-mobile.png' })
  await page.getByRole('button', { name: '简体' }).click()
})
