#!/usr/bin/env node
/**
 * Tabbit CLI E2E UI Verification & PR Screenshot Generator for Resume-Agent.
 *
 * Drives the local frontend via `tabbit-cli nodejs`, walks through 4 core UI
 * scenarios, captures viewport screenshots, and outputs verified paths.
 */

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const TABBIT_CLI =
  process.env.TABBIT_CLI || path.join(os.homedir(), ".local/bin/tabbit-cli");
const BASE_URL = process.env.BASE_URL || "http://127.0.0.1:5173/";
const OUT_DIR = process.env.OUT_DIR || "/tmp/resume-tabbit-verify";
const RUN_ID = Math.floor(Date.now() / 1000);
const TASK_NAME = `ResumeAgent-Verify-${RUN_ID}`;

if (!fs.existsSync(TABBIT_CLI)) {
  console.error(`Error: tabbit-cli not found at ${TABBIT_CLI}`);
  process.exit(1);
}

fs.mkdirSync(OUT_DIR, { recursive: true });

const script = `
await page.goto(${JSON.stringify(BASE_URL)}, { waitUntil: "domcontentloaded" });
await page.waitForSelector("h1", { timeout: 10000 });
await page.waitForTimeout(500);
await page.screenshot({ path: ${JSON.stringify(path.join(OUT_DIR, "01-home.png"))} });

const changelogBtn = page.locator('button[title*="更新日志"], button:has-text("更新")').first();
await changelogBtn.click({ timeout: 5000 });
await page.waitForTimeout(600);
await page.screenshot({ path: ${JSON.stringify(path.join(OUT_DIR, "02-changelog-page.png"))} });

await page.goto(${JSON.stringify(BASE_URL)}, { waitUntil: "domcontentloaded" });
await page.waitForSelector("h1", { timeout: 10000 });
await page.waitForTimeout(400);

const skinBtn = page.locator('button[title*="界面皮肤"], button:has-text("皮肤")').first();
await skinBtn.click({ timeout: 5000 });
await page.waitForTimeout(400);
await page.screenshot({ path: ${JSON.stringify(path.join(OUT_DIR, "03-skin-picker.png"))} });
await skinBtn.click({ timeout: 2000, force: true }).catch(() => {});
await page.waitForTimeout(300);

const input = page.getByRole("textbox").first();
await input.fill("3年 Go 与 React 全栈开发经验，主导过 AI Agent 平台建设，求职高级全栈工程师", { timeout: 5000 });
await page.waitForTimeout(300);
const startBtn = page.locator('button:has-text("开始")').first();
const disabled = await startBtn.isDisabled({ timeout: 5000 });
await page.screenshot({ path: ${JSON.stringify(path.join(OUT_DIR, "04-input-active.png"))} });

return {
  title: await page.title(),
  startButtonDisabled: disabled,
  verified: !disabled,
};
`;

console.log(`Running 4 Tabbit UI scenarios (Task: ${TASK_NAME})...`);
const stdout = execFileSync(
  TABBIT_CLI,
  ["nodejs", "--task", TASK_NAME, "--request-id", `verify-all-${RUN_ID}`],
  { input: script, encoding: "utf8" }
);

const jsonLine = stdout
  .split("\n")
  .map((l) => l.trim())
  .filter((l) => l.startsWith("{"))
  .pop();

if (!jsonLine) {
  console.error("Failed to parse Tabbit CLI JSON output");
  process.exit(1);
}

const result = JSON.parse(jsonLine);
if (result.status !== "succeeded") {
  console.error("Tabbit execution failed:", JSON.stringify(result, null, 2));
  process.exit(1);
}

const names = [
  "01-home.png",
  "02-changelog-page.png",
  "03-skin-picker.png",
  "04-input-active.png",
];
const deltas = result.result?.screenshotsDelta || [];
deltas.forEach((shot, i) => {
  if (i < names.length) {
    const dest = path.join(OUT_DIR, names[i]);
    fs.copyFileSync(shot.path, dest);
    console.log(`  [${i + 1}/4] Saved: ${dest}`);
  }
});

console.log("Assertion result:", JSON.stringify(result.result?.value));

try {
  execFileSync(TABBIT_CLI, ["finish", "--task", TASK_NAME], { stdio: "ignore" });
} catch {}
