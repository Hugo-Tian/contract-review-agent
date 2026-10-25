import { defineConfig } from '@playwright/test'
export default defineConfig({testDir:'./tests',workers:1,use:{browserName:'chromium',channel:'msedge',headless:true},reporter:'list'})
