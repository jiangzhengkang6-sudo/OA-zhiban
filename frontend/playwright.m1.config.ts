import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir:'./e2e', testMatch:'m1-identity.spec.ts', fullyParallel:false, workers:1, timeout:60000,
  reporter:[['list'],['json',{outputFile:'../data/verification/m1/browser-result.json'}]],
  use:{baseURL:'http://127.0.0.1:5193',channel:'msedge',...devices['Desktop Chrome'],trace:'off',screenshot:'off'},
  outputDir:'../data/verification/m1/browser-output',
})
