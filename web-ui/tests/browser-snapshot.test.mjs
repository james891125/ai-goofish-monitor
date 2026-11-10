import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, nextTick } from 'vue'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const toModule = source => `data:text/javascript;base64,${Buffer.from(ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText).toString('base64')}`
const helpersUrl = toModule(read('../src/lib/shopee.ts'))
const { browserProductUrl, buildBrowserRequest, buildBrowserImport, newTask, validateTask } = await import(helpersUrl)
const snapshotProvider = { id: 'browser_experiment', available: true, capabilities: { keyword: true, price: true } }
const product = { product_id: '123_456', title: '離線合成測試商品', price_twd: 15000, product_url: 'https://shopee.tw/product/123/456', images: [], images_allowed: false }

test('collector request supports exactly one input and has the agreed wire fields', () => {
  assert.deepEqual(buildBrowserRequest('  Mac mini M4  ', '', 120, 5), { keyword: 'Mac mini M4', urls: [], interval_seconds: 120, max_items: 5 })
  assert.deepEqual(buildBrowserRequest('', 'https://www.shopee.tw/商品-i.123.456?tracking=discard#details\nhttps://shopee.tw/product/5/6', 60, 1), {
    keyword: null, urls: ['https://shopee.tw/product/123/456', 'https://shopee.tw/product/5/6'], interval_seconds: 60, max_items: 1,
  })
  for (const [keyword, urls] of [['', ''], ['   ', '\n'], ['Mac', product.product_url]]) assert.throws(() => buildBrowserRequest(keyword, urls, 120, 5), /擇一/)
  assert.throws(() => buildBrowserRequest('x'.repeat(201), '', 120, 5), /200/)
  assert.throws(() => buildBrowserRequest('Mac\nmini', '', 120, 5), /控制字元/)
})

test('collector request enforces bounded integers and URL counts without silent truncation', () => {
  for (const value of [0, 59, 301, 60.5, Number.NaN, Number.POSITIVE_INFINITY, '60']) assert.throws(() => buildBrowserRequest('Mac', '', value, 1), /60 至 300/)
  for (const value of [0, 6, 1.5, Number.NaN, Number.POSITIVE_INFINITY, '1']) assert.throws(() => buildBrowserRequest('Mac', '', 60, value), /1 至 5/)
  assert.equal(buildBrowserRequest('Mac', '', 300, 5).interval_seconds, 300)
  const five = Array.from({ length: 5 }, (_, i) => `https://shopee.tw/product/123/${i + 1}`).join('\n')
  assert.equal(buildBrowserRequest('', five, 60, 5).urls.length, 5)
  assert.throws(() => buildBrowserRequest('', `${five}\nhttps://shopee.tw/product/123/9`, 60, 5), /1 至 5/)
  assert.throws(() => buildBrowserRequest('', `${product.product_url}\nhttps://www.shopee.tw/test-i.123.456?trace=1`, 60, 5), /重複/)
})

test('only normal Taiwanese product links survive canonicalization', () => {
  assert.equal(browserProductUrl('https://shopee.tw:443/product/123/456?x=y#info'), product.product_url)
  assert.equal(browserProductUrl('https://shopee.tw/%E5%95%86%E5%93%81-i.123.456'), product.product_url)
  for (const value of [
    'https://shopee.tw/', 'https://shopee.tw/search?keyword=Mac', 'https://shopee.tw/buyer/login',
    'https://shopee.tw/product/0/456', 'https://shopee.tw/product/123/-1', 'https://shopee.tw/product/123/456/extra',
    'https://shopee.tw/product/123/456/../../123/456', 'https://shopee.tw/login/../product/123/456',
    'https://shopee.tw/product%2F123%2F456', 'https://shopee.tw/%2e%2e/product/123/456',
    'https://shopee.tw/%01evil-i.123.456', 'https://shopee.tw/%5Cevil-i.123.456', 'https://shopee.tw/%zz-i.123.456',
    'https://user:pass@shopee.tw/product/123/456', 'https://shopee.tw:8443/product/123/456',
    'https://shopee.tw.evil.test/product/123/456', 'https://evil.shopee.tw/product/123/456',
    'http://shopee.tw/product/123/456', 'https://s.shopee.tw/example', 'javascript:alert(1)',
    'https://shopee.tw\\@evil.test/product/123/456', 'https://shopee.tw/\nproduct/123/456',
  ]) assert.equal(browserProductUrl(value), undefined, value)
})

test('snapshot imports require both exact confirmations and one to five objects', () => {
  const content = JSON.stringify({ source: 'browser_experiment', products: [product], status: 'complete' })
  for (const [rights, risk] of [[false, false], [true, false], [false, true]]) assert.throws(() => buildBrowserImport(content, rights, risk), /分別確認/)
  assert.deepEqual(buildBrowserImport(content, true, true), { products: [product], rights_confirmed: true, risk_confirmed: true })
  assert.equal(buildBrowserImport(JSON.stringify(Array(5).fill(product)), true, true).products.length, 5)
  assert.throws(() => buildBrowserImport(JSON.stringify(Array(6).fill(product)), true, true), /最多匯入 5/)
  for (const content of ['[]', '{}', '[null]', '[[]]', '[1]', '["abc"]', 'invalid']) assert.throws(() => buildBrowserImport(content, true, true))
})

test('snapshot tasks cannot schedule, paginate or analyze more than five items', () => {
  const task = { ...newTask(), task_name: '快照測試', keyword: 'Mac', description: '檢查規格與風險', provider: 'browser_experiment', max_items: 5, max_pages: 1 }
  assert.deepEqual(validateTask(task, snapshotProvider), [])
  assert.deepEqual(validateTask({ ...task, decision_mode: 'ai', description: '檢查規格' }, snapshotProvider), [])
  assert.match(validateTask({ ...task, decision_mode: 'keyword' }, snapshotProvider).join(), /保留 AI 分析/)
  assert.equal(validateTask({ ...task, cron: '*/30 * * * *', max_items: 6, max_pages: 2 }, snapshotProvider).length, 3)
  assert.match(validateTask({ ...task, cron: '' }, snapshotProvider).join(), /不支援排程/)
  assert.equal(validateTask({ ...task, max_items: 0 }, snapshotProvider).length, 1)
  assert.deepEqual(validateTask({ ...task, provider: 'import', cron: '*/30 * * * *', max_items: 500, max_pages: 20 }, { ...snapshotProvider, id: 'import' }), [])
})

test('API keeps ordinary import unchanged and sends a distinct dual-confirmed snapshot payload', async () => {
  const calls = []
  globalThis.__snapshotHttp = async (...args) => { calls.push(args); return { imported: 1 } }
  try {
    const source = read('../src/api/shopee.ts').replace("import { http } from '@/lib/http'", 'const http = globalThis.__snapshotHttp')
    const { shopeeApi } = await import(toModule(source))
    await shopeeApi.importProducts([product])
    await shopeeApi.importBrowserProducts(buildBrowserImport(JSON.stringify([product]), true, true))
    assert.equal(calls[0][0], '/api/shopee/import')
    assert.deepEqual(JSON.parse(calls[0][1].body), { products: [product], rights_confirmed: true })
    assert.equal(calls[1][0], '/api/shopee/browser-import')
    assert.equal(calls[1][1].method, 'POST')
    assert.deepEqual(JSON.parse(calls[1][1].body), { products: [product], rights_confirmed: true, risk_confirmed: true })
  } finally { delete globalThis.__snapshotHttp }
})

// Exercise the production component's setup state with Vue's headless renderer.
// No browser, website, screenshot, network, shell, or extra test dependency.
const renderer = createRenderer({
  createComment: text => ({ text }), createText: text => ({ text }), createElement: type => ({ type }),
  insert: () => {}, remove: () => {}, setText: () => {}, setElementText: () => {}, patchProp: () => {}, parentNode: () => null, nextSibling: () => null,
})
let fixtureId = 0
async function snapshotFixture(api, available = true) {
  const source = read('../src/components/shopee/BrowserSnapshotPanel.vue').replace("import { shopeeApi } from '@/api/shopee'", 'const shopeeApi = globalThis.__snapshotTestApi')
  const { descriptor } = parse(source)
  const script = compileScript(descriptor, { id: `snapshot-test-${++fixtureId}` })
  const compiled = script.content
    .replaceAll("from 'vue'", `from ${JSON.stringify(import.meta.resolve('vue'))}`)
    .replaceAll('from "vue"', `from ${JSON.stringify(import.meta.resolve('vue'))}`)
    .replaceAll("from 'lucide-vue-next'", `from ${JSON.stringify(import.meta.resolve('lucide-vue-next'))}`)
    .replaceAll("from '@/lib/shopee'", `from ${JSON.stringify(helpersUrl)}`)
  const { default: component } = await import(toModule(compiled + `\n// fixture ${fixtureId}`))
  const emitted = []
  globalThis.__snapshotTestApi = api
  const app = renderer.createApp({ ...component, render: () => null }, { available, onImported: count => emitted.push(count) })
  const instance = app.mount({})
  delete globalThis.__snapshotTestApi
  return { app, state: instance.$.setupState, emitted }
}

async function editorFixture(task, aiConfigured = true) {
  const { descriptor } = parse(read('../src/components/shopee/TaskEditor.vue'))
  const script = compileScript(descriptor, { id: `editor-test-${++fixtureId}` })
  const compiled = script.content
    .replaceAll("from 'vue'", `from ${JSON.stringify(import.meta.resolve('vue'))}`)
    .replaceAll('from "vue"', `from ${JSON.stringify(import.meta.resolve('vue'))}`)
    .replaceAll("from 'lucide-vue-next'", `from ${JSON.stringify(import.meta.resolve('lucide-vue-next'))}`)
    .replaceAll("from '@/lib/shopee'", `from ${JSON.stringify(helpersUrl)}`)
  const { default: component } = await import(toModule(compiled + `\n// fixture ${fixtureId}`))
  const emitted = []
  const providers = [snapshotProvider, { id: 'mock', available: true, capabilities: {} }]
  const app = renderer.createApp({ ...component, render: () => null }, { task, providers, aiConfigured, busy: false, error: '', timezone: 'Asia/Taipei', onSave: value => emitted.push(value) })
  const instance = app.mount({})
  return { app, state: instance.$.setupState, emitted }
}

test('TaskEditor switches to bounded manual AI snapshots without changing the source task', async () => {
  const original = { ...newTask(), task_name: '舊任務', keyword: 'Mac', description: '檢查規格', decision_mode: 'keyword', cron: '*/30 * * * *', analyze_images: true }
  const { app, state, emitted } = await editorFixture(original)
  try {
    assert.equal(state.draft.decision_mode, 'keyword')
    assert.equal(state.draft.cron, original.cron)
    state.draft.provider = 'browser_experiment'
    await nextTick()
    assert.equal(state.draft.decision_mode, 'ai')
    assert.equal(state.draft.max_items, 5)
    assert.equal(state.draft.max_pages, 1)
    assert.equal(state.draft.cron, null)
    assert.equal(state.schedule, '')
    assert.equal(state.cron, '')
    assert.equal(state.draft.analyze_images, false)
    state.save()
    assert.equal(emitted.length, 1)
    assert.equal(emitted[0].cron, null)
    assert.equal(emitted[0].decision_mode, 'ai')
    assert.equal(original.provider, 'mock')
    assert.equal(original.decision_mode, 'keyword')
    assert.equal(original.max_items, 50)
    assert.equal(original.cron, '*/30 * * * *')
  } finally { app.unmount() }
})

test('TaskEditor requires AI configuration and purchase requirements without silent fallback', async () => {
  const { app, state, emitted } = await editorFixture({ ...newTask(), provider: 'browser_experiment', task_name: 'AI 快照', keyword: 'Mac' }, false)
  try {
    state.save()
    assert.equal(emitted.length, 0)
    assert.ok(state.errors.some(value => value.includes('詳細購買需求')))
    assert.ok(state.errors.some(value => value.includes('設定 AI 服務')))
    assert.equal(state.draft.decision_mode, 'ai')
  } finally { app.unmount() }
})

test('snapshot UI starts unchecked and editing JSON invalidates both confirmations', async () => {
  const { app, state } = await snapshotFixture({})
  try {
    assert.equal(state.rightsConfirmed, false)
    assert.equal(state.riskConfirmed, false)
    state.importContent = JSON.stringify([product])
    state.rightsConfirmed = true; state.riskConfirmed = true
    state.importContent += ' '
    assert.equal(state.rightsConfirmed, false)
    assert.equal(state.riskConfirmed, false)
    assert.equal(state.requestState.request, null)
    state.keyword = 'Mac'
    assert.equal(state.requestState.request.keyword, 'Mac')
    state.urls = product.product_url
    assert.match(state.requestState.error, /擇一/)
  } finally { app.unmount() }
})

test('request download creates only the bounded local JSON file, not a network operation', async t => {
  const { app, state } = await snapshotFixture({ importBrowserProducts: () => assert.fail('A request download must not import or browse') })
  const oldDocument = globalThis.document
  const hadDocument = Object.hasOwn(globalThis, 'document')
  const anchor = { click: t.mock.fn(), remove: t.mock.fn() }
  const appendChild = t.mock.fn()
  globalThis.document = { createElement: tag => { assert.equal(tag, 'a'); return anchor }, body: { appendChild } }
  const create = t.mock.method(URL, 'createObjectURL', () => 'blob:offline-test')
  const revoke = t.mock.method(URL, 'revokeObjectURL', () => {})
  let release
  t.mock.method(globalThis, 'setTimeout', (callback, delay) => { assert.equal(delay, 1000); release = callback; return 1 })
  try {
    state.downloadRequest()
    assert.equal(create.mock.callCount(), 0)
    state.keyword = 'Mac mini M4'
    state.intervalSeconds = 300
    state.maxItems = 2
    state.downloadRequest()
    assert.equal(create.mock.callCount(), 1)
    const blob = create.mock.calls[0].arguments[0]
    assert.deepEqual(JSON.parse(await blob.text()), { keyword: 'Mac mini M4', urls: [], interval_seconds: 300, max_items: 2 })
    assert.equal(anchor.href, 'blob:offline-test')
    assert.equal(anchor.download, 'browser-request.json')
    assert.equal(appendChild.mock.callCount(), 1)
    assert.equal(anchor.click.mock.callCount(), 1)
    assert.equal(anchor.remove.mock.callCount(), 1)
    assert.match(state.downloadStatus, /瀏覽器尚未啟動/)
    release()
    assert.equal(revoke.mock.calls[0].arguments[0], 'blob:offline-test')
  } finally {
    app.unmount()
    if (hadDocument) globalThis.document = oldDocument
    else delete globalThis.document
  }
})

test('an unavailable snapshot provider cannot receive an import', async () => {
  const { app, state } = await snapshotFixture({ importBrowserProducts: () => assert.fail('Unavailable provider must not receive imports') }, false)
  try {
    state.importContent = JSON.stringify([product]); state.rightsConfirmed = true; state.riskConfirmed = true
    assert.equal(state.importDisabled, true)
    await state.importSnapshots()
    assert.equal(state.importContent, JSON.stringify([product]))
  } finally { app.unmount() }
})

test('snapshot UI never imports without both confirmations and guards repeated clicks', async () => {
  const calls = []
  let finish
  const pending = new Promise(resolve => { finish = resolve })
  const { app, state, emitted } = await snapshotFixture({ importBrowserProducts: payload => { calls.push(payload); return pending } })
  try {
    state.importContent = JSON.stringify([product])
    state.rightsConfirmed = true
    await state.importSnapshots()
    assert.equal(calls.length, 0)
    assert.match(state.importError, /分別確認/)
    state.riskConfirmed = true
    const first = state.importSnapshots()
    assert.equal(state.importBusy, true)
    await state.importSnapshots()
    assert.equal(calls.length, 1)
    assert.deepEqual(calls[0], { products: [product], rights_confirmed: true, risk_confirmed: true })
    finish({ imported: 1 })
    await first
    assert.deepEqual(emitted, [1])
    assert.equal(state.importContent, '')
    assert.equal(state.rightsConfirmed, false)
    assert.equal(state.riskConfirmed, false)
    assert.equal(state.importBusy, false)
  } finally { app.unmount() }
})

test('snapshot UI preserves failed imports without automatically retrying', async () => {
  let attempts = 0
  const { app, state } = await snapshotFixture({ importBrowserProducts: async () => { attempts++; throw new Error('測試匯入拒絕') } })
  try {
    const content = JSON.stringify([product])
    state.importContent = content; state.rightsConfirmed = true; state.riskConfirmed = true
    await state.importSnapshots()
    await nextTick()
    assert.equal(attempts, 1)
    assert.equal(state.importContent, content)
    assert.equal(state.importBusy, false)
    assert.match(state.importError, /測試匯入拒絕/)
    state.importContent = JSON.stringify(Array(6).fill(product)); state.rightsConfirmed = true; state.riskConfirmed = true
    await state.importSnapshots()
    assert.equal(attempts, 1)
    assert.match(state.importError, /最多匯入 5/)
  } finally { app.unmount() }
})

test('file reads reset consent, reject oversized files, and do not complete after unmount', async () => {
  const { app, state } = await snapshotFixture({})
  let finish
  const pending = new Promise(resolve => { finish = resolve })
  state.importContent = 'old'; state.rightsConfirmed = true; state.riskConfirmed = true
  await state.readFile({ target: { files: [{ size: 5 * 1024 * 1024 + 1 }], value: 'large.json' } })
  assert.match(state.importError, /5 MB/)
  assert.equal(state.rightsConfirmed, false)
  assert.equal(state.riskConfirmed, false)
  const reading = state.readFile({ target: { files: [{ size: 4, text: () => pending }], value: 'snapshot.json' } })
  assert.equal(state.readingFile, true)
  assert.equal(state.importDisabled, true)
  app.unmount()
  finish('new')
  await reading
  assert.equal(state.importContent, 'old')
})

test('snapshot UI documents exact manual commands and preserves the release warning', () => {
  const component = read('../src/components/shopee/BrowserSnapshotPanel.vue')
  const view = read('../src/views/ShopeeView.vue')
  assert.ok(component.includes('.\\.venv\\Scripts\\python.exe -m pip install -r requirements-browser.txt'))
  assert.ok(component.includes('.\\.venv\\Scripts\\python.exe scripts/browser_collect.py --request browser-request.json --output browser-results.json --channel msedge'))
  assert.ok(component.includes("anchor.download = 'browser-request.json'"))
  assert.ok(component.includes('不會自動重試、繞過或切換帳號'))
  assert.ok(view.includes('<strong>等待資料來源授權</strong>'))
  assert.ok(view.includes('重新分析快照'))
  assert.ok(view.includes('實驗功能：平台授權尚未驗證'))
  assert.ok(view.includes('run.ai_new_count ?? 0'))
  assert.ok(view.includes('run.ai_reused_count ?? 0'))
  assert.ok(view.includes('run.ai_skipped_count ?? 0'))
})
