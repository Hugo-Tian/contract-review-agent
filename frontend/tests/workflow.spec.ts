import { test, expect } from '@playwright/test'
import path from 'node:path'

test('paste, revise, demo, locate, copy and clear',async({page})=>{
  await page.goto('http://127.0.0.1:8000')
  await page.getByRole('button',{name:'填入虚构示例'}).click()
  await page.getByRole('button',{name:'提取并核对正文'}).click()
  await expect(page.getByRole('heading',{name:'先核对，再分析'})).toBeVisible()
  await page.locator('.edit-block textarea').first().fill('用户校正：虚构示例合同')
  await page.getByRole('button',{name:'保存修订并生成新版本'}).click()
  await expect(page.getByText('用户修订',{exact:true})).toBeVisible()
  await page.getByRole('checkbox',{name:'我已核对正文与金额对应关系，了解上述覆盖范围。'}).check()
  await page.getByRole('combobox',{name:'运行方式',exact:true}).selectOption('demo')
  await page.getByRole('button',{name:'查看演示报告'}).click()
  await expect(page.getByText('演示报告 · 未分析合同',{exact:true})).toBeVisible()
  await page.locator('.quote').first().click()
  await expect(page.locator('.source-block.highlighted')).toContainText('用户校正')
  await page.getByRole('button',{name:'复制微信草稿'}).click()
  await page.getByRole('button',{name:'清除本次文档与页面报告'}).click()
  await expect(page.getByRole('heading',{name:'导入你的合同'})).toBeVisible()
})

for(const ext of ['pdf','docx']) test(`upload ${ext} full workflow`,async({page})=>{
  await page.goto('http://127.0.0.1:8000')
  await page.locator('input[type=file]').setInputFiles(path.resolve('../examples/fictional-contract.'+ext))
  await expect(page.getByRole('heading',{name:'先核对，再分析'})).toBeVisible()
  await page.getByRole('checkbox',{name:'我已核对正文与金额对应关系，了解上述覆盖范围。'}).check()
  await page.getByRole('combobox',{name:'运行方式',exact:true}).selectOption('demo')
  await page.getByRole('button',{name:'查看演示报告'}).click()
  await expect(page.getByText('演示报告 · 未分析合同',{exact:true})).toBeVisible()
  await expect(page.locator('.source-panel')).toContainText('9800')
})

test('mobile fits viewport',async({page})=>{
  await page.setViewportSize({width:390,height:844})
  await page.goto('http://127.0.0.1:8000')
  await expect(page.getByRole('heading',{name:'导入你的合同'})).toBeVisible()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:'../work/mobile.png',fullPage:true})
})
