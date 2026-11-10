import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'

// Exercise the production pure helpers without adding a second test toolchain.
const source = readFileSync(new URL('../src/lib/shopee.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText
const { newTask, sampleTask, validateTask, sanitizeCapabilities, formatPrice, formatDate, safeProductUrl, safeImageUrl, parseImport, scheduleLabel } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
const provider = { id: 'mock', available: true, capabilities: {} }
const task = () => ({ ...newTask(), task_name: '測試任務', keyword: 'RTX 5070 Ti' })

test('new tasks use safe mock and keyword defaults', () => {
  assert.equal(newTask().provider, 'mock')
  assert.equal(newTask().decision_mode, 'keyword')
  assert.equal(newTask().cron, null)
  assert.deepEqual(validateTask(task(), provider), [])
})
test('validates names, source, limits, price ranges and cron', () => {
  assert.equal(validateTask({ ...task(), task_name: ' ', keyword: '', min_price: 300, max_price: 100, max_items: 501, max_pages: 21, cron: '* *' }, { available: false }).length, 7)
  assert.equal(validateTask({ ...task(), min_price: -1, max_price: Number.NaN }, provider).length, 2)
  assert.equal(validateTask({ ...task(), max_items: 1.5, max_pages: 0 }, provider).length, 2)
  assert.equal(validateTask({ ...task(), decision_mode: 'ai', description: '' }, provider).length, 1)
})
test('unsupported capability filters are cleared rather than fabricated', () => {
  const filtered = sanitizeCapabilities({ ...task(), category: 'gpu', condition: 'used', region: '臺北市', seller_type: 'personal', exclude_ads: true }, provider)
  assert.equal(filtered.category, null)
  assert.equal(filtered.condition, null)
  assert.equal(filtered.region, null)
  assert.equal(filtered.seller_type, null)
  assert.equal(filtered.exclude_ads, false)
  const supported = { ...provider, capabilities: { category: true, condition: true, region: true, seller_type: true, ads: true } }
  assert.equal(sanitizeCapabilities({ ...task(), region: '臺北市' }, supported).region, '臺北市')
})
test('sample tasks match requested presets without claiming live data', () => {
  assert.equal(sampleTask('rtx').min_price, 15000)
  assert.equal(sampleTask('rtx').cron, '*/30 * * * *')
  assert.equal(sampleTask('mac').max_price, null)
  assert.equal(sampleTask('mac').provider, 'mock')
  assert.ok(sampleTask('mac').exclude_keywords.includes('空盒'))
  assert.equal(scheduleLabel(null), '僅手動執行')
})
test('prices and timestamps use Taiwan presentation', () => {
  assert.equal(formatPrice(15000), 'NT$15,000')
  assert.equal(formatPrice(0), 'NT$0')
  assert.equal(formatPrice(null), '未提供價格')
  assert.equal(formatDate('bad-date'), '無效時間')
  assert.match(formatDate('2026-11-10T00:00:00Z'), /08:00:00/)
})
test('links reject scripts, credentials, ports and unrelated sites', () => {
  assert.equal(safeProductUrl('https://shopee.tw/product/1/2'), 'https://shopee.tw/product/1/2')
  for (const value of ['javascript:alert(1)', 'https://shopee.tw.evil.test/', 'https://evil.shopee.tw/', 'http://shopee.tw/', 'https://x:y@shopee.tw/', 'https://shopee.tw:8443/']) assert.equal(safeProductUrl(value), undefined)
  assert.ok(safeImageUrl('https://down-tw.img.susercontent.com/file/test'))
  assert.equal(safeImageUrl('https://attacker.test/image.png'), undefined)
  assert.equal(safeImageUrl('data:image/svg+xml,test'), undefined)
})
test('imports require nonempty bounded JSON arrays', () => {
  assert.deepEqual(parseImport('[{"title":"test"}]'), [{ title: 'test' }])
  assert.deepEqual(parseImport('{"products":[{"title":"test"}]}'), [{ title: 'test' }])
  for (const value of ['[]', '{}', 'null', '"abc"', 'bad']) assert.throws(() => parseImport(value))
  assert.throws(() => parseImport(JSON.stringify(Array.from({ length: 501 }, () => ({})))))
})
