#!/usr/bin/env node

/**
 * check-changelog.mjs
 * 
 * 自动化工程治理脚本：
 * 验证 frontend/src/data/changelog.ts 中的版本更新日志
 * 严格执行纯日期规范（YYYY-MM-DD，严禁携带时间戳）与 SemVer 规范。
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// 默认定位到仓库根目录下的 frontend/src/data/changelog.ts
const repoRoot = path.resolve(__dirname, '..');
const defaultChangelogPath = path.join(repoRoot, 'frontend', 'src', 'data', 'changelog.ts');

const args = process.argv.slice(2);
let changelogPath = defaultChangelogPath;
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--file' && args[i + 1]) {
    changelogPath = path.resolve(process.cwd(), args[i + 1]);
    i++;
  }
}

if (!fs.existsSync(changelogPath)) {
  console.error(`[ERROR] Changelog file not found at: ${changelogPath}`);
  process.exit(1);
}

const content = fs.readFileSync(changelogPath, 'utf-8');

// 正则表达式
const PURE_DATE_REGEX = /^\d{4}-\d{2}-\d{2}$/;
const SEMVER_REGEX = /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$/;

/**
 * 比较两个语义化版本
 * 返回 > 0 表示 v1 > v2; < 0 表示 v1 < v2; 0 表示相等
 */
function compareSemver(v1, v2) {
  const m1 = v1.match(SEMVER_REGEX);
  const m2 = v2.match(SEMVER_REGEX);
  if (!m1 || !m2) return 0;

  const [maj1, min1, pat1] = [parseInt(m1[1], 10), parseInt(m1[2], 10), parseInt(m1[3], 10)];
  const [maj2, min2, pat2] = [parseInt(m2[1], 10), parseInt(m2[2], 10), parseInt(m2[3], 10)];

  if (maj1 !== maj2) return maj1 - maj2;
  if (min1 !== min2) return min1 - min2;
  if (pat1 !== pat2) return pat1 - pat2;
  return 0;
}

/**
 * 解析 changelog.ts 文本中的条目
 */
function extractEntries(source) {
  const entries = [];
  // 查找 CHANGELOG = [ ... ] 区域（避开顶部注释）
  const match = source.match(/\bCHANGELOG\s*(?::\s*[^=]+)?\s*=\s*\[/);
  if (!match || match.index === undefined) {
    throw new Error('Could not find CHANGELOG array assignment in file.');
  }

  const arrayStart = match.index + match[0].length - 1;

  let depth = 0;
  let inString = false;
  let stringChar = '';
  let objStart = -1;

  for (let i = arrayStart; i < source.length; i++) {
    const ch = source[i];
    const prev = i > 0 ? source[i - 1] : '';

    if (inString) {
      if (ch === stringChar && prev !== '\\') {
        inString = false;
      }
      continue;
    }

    if (ch === '"' || ch === "'" || ch === '`') {
      inString = true;
      stringChar = ch;
      continue;
    }

    if (ch === '[') {
      depth++;
    } else if (ch === ']') {
      depth--;
      if (depth === 0) break;
    } else if (ch === '{') {
      if (depth === 1) {
        objStart = i;
      }
    } else if (ch === '}') {
      if (depth === 1 && objStart !== -1) {
        const objText = source.slice(objStart, i + 1);
        entries.push({
          raw: objText,
          line: source.slice(0, objStart).split('\n').length,
        });
        objStart = -1;
      }
    }
  }

  return entries;
}

function parseEntryFields(raw) {
  // 提取 version: '...'
  const versionMatch = raw.match(/version:\s*['"]([^'"]+)['"]/);
  // 提取 date: '...'
  const dateMatch = raw.match(/date:\s*['"]([^'"]+)['"]/);

  // 提取 added: [ ... ]
  const hasAdded = /added:\s*\[/.test(raw);
  // 提取 fixed: [ ... ]
  const hasFixed = /fixed:\s*\[/.test(raw);

  return {
    version: versionMatch ? versionMatch[1] : null,
    date: dateMatch ? dateMatch[1] : null,
    hasContent: hasAdded || hasFixed,
  };
}

// 执行验证
const rawEntries = extractEntries(content);
const errors = [];
const parsedEntries = [];

for (const item of rawEntries) {
  const fields = parseEntryFields(item.raw);

  if (!fields.version) {
    errors.push(`Line ${item.line}: Missing 'version' field in entry.`);
    continue;
  }

  // 1. 验证 SemVer
  if (!SEMVER_REGEX.test(fields.version)) {
    errors.push(
      `Line ${item.line} (version ${fields.version}): Invalid semver format. Expected X.Y.Z (e.g. 3.10.0).`
    );
  }

  // 2. 验证纯日期 (YYYY-MM-DD，严禁携带时间)
  if (!fields.date) {
    errors.push(`Line ${item.line} (version ${fields.version}): Missing 'date' field.`);
  } else if (!PURE_DATE_REGEX.test(fields.date)) {
    errors.push(
      `Line ${item.line} (version ${fields.version}): Invalid date format '${fields.date}'. ` +
      `Must strictly match pure date YYYY-MM-DD (e.g. '2026-11-15'). Timestamps are strictly forbidden.`
    );
  } else {
    // 验证日历合法性
    const [y, m, d] = fields.date.split('-').map(Number);
    if (m < 1 || m > 12 || d < 1 || d > 31) {
      errors.push(
        `Line ${item.line} (version ${fields.version}): Calendar date out of bounds '${fields.date}'.`
      );
    }
  }

  // 3. 验证是否有内容
  if (!fields.hasContent) {
    errors.push(
      `Line ${item.line} (version ${fields.version}): Entry must contain at least one of 'added' or 'fixed'.`
    );
  }

  parsedEntries.push({ ...fields, line: item.line });
}

// 4. 验证版本单调递减（最新版本在数组首项）
for (let i = 0; i < parsedEntries.length - 1; i++) {
  const curr = parsedEntries[i];
  const next = parsedEntries[i + 1];

  if (curr.version && next.version && SEMVER_REGEX.test(curr.version) && SEMVER_REGEX.test(next.version)) {
    const cmp = compareSemver(curr.version, next.version);
    if (cmp <= 0) {
      errors.push(
        `Version ordering violation at line ${curr.line}: version '${curr.version}' is not greater than preceding version '${next.version}' at line ${next.line}. ` +
        `Newer versions must appear higher in the CHANGELOG array.`
      );
    }
  }
}

// 输出结果
console.log('='.repeat(70));
console.log(`[CHANGELOG VALIDATION] Auditing: ${changelogPath}`);
console.log(`Total release entries found: ${parsedEntries.length}`);

if (parsedEntries.length > 0) {
  console.log(`Latest release: v${parsedEntries[0].version} (${parsedEntries[0].date})`);
  console.log(`Initial release: v${parsedEntries[parsedEntries.length - 1].version} (${parsedEntries[parsedEntries.length - 1].date})`);
}

if (errors.length > 0) {
  console.error('\n❌ CHANGELOG VALIDATION FAILED WITH ERRORS:');
  for (const err of errors) {
    console.error(`  - ${err}`);
  }
  console.log('='.repeat(70));
  process.exit(1);
}

console.log('✅ ALL CHANGELOG ENTRIES PASSED PURE-DATE AND SEMVER VALIDATION (Exit Code 0).');
console.log('='.repeat(70));
process.exit(0);
