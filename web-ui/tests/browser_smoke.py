"""Local Chromium end-to-end smoke against an isolated temporary app.

Run after `npm run build`: .venv/bin/python web-ui/tests/browser_smoke.py
Requires Python requirements and Playwright, with Chromium installed. Set
CHROMIUM_EXECUTABLE for a system Chromium; defaults to /usr/bin/chromium
when present, otherwise the Playwright-managed browser. No live services used.
"""
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
SCREENSHOTS = ROOT / 'docs' / 'screenshots'


def run():
    if not (ROOT / 'dist' / 'index.html').exists():
        raise SystemExit('請先執行 npm run build。')
    with tempfile.TemporaryDirectory(prefix='shopee-browser-test-') as temporary:
        work = Path(temporary)
        shutil.copytree(ROOT / 'dist', work / 'dist')
        shutil.copytree(ROOT / 'prompts', work / 'prompts')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        password = secrets.token_urlsafe(24)
        env = {key: value for key, value in os.environ.items() if not key.startswith(('OPENAI_', 'DISCORD_'))}
        env.update(PYTHONPATH=str(ROOT), APP_DATABASE_FILE=str(work / 'test.sqlite3'), WEB_USERNAME='ui-tester', WEB_PASSWORD=password)
        log = (work / 'server.log').open('w+')
        server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'src.app:app', '--host', '127.0.0.1', '--port', str(port)], cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT)
        url = f'http://127.0.0.1:{port}'
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(url + '/health', timeout=1)
                    break
                except Exception:
                    if server.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(log.read())
                    time.sleep(.1)
            else:
                raise RuntimeError('測試後端啟動逾時。')
            with sync_playwright() as pw:
                executable = os.getenv('CHROMIUM_EXECUTABLE') or shutil.which('chromium')
                browser = pw.chromium.launch(headless=True, executable_path=executable)
                context = browser.new_context(viewport={'width': 1440, 'height': 1050}, locale='zh-TW')
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(url)
                expect(page.get_by_role('heading', name='登入監控中心')).to_be_visible()
                page.get_by_label('管理員帳號').fill('ui-tester')
                page.get_by_label('密碼', exact=True).fill(password)
                page.get_by_role('button', name='登入', exact=True).click()
                expect(page.get_by_role('heading', name='監控任務', exact=True)).to_be_visible()
                expect(page.get_by_text('等待資料來源授權', exact=True)).to_be_visible()
                expect(page.get_by_text('從第一個監控任務開始')).to_be_visible()
                page.get_by_role('button', name=re.compile('顯示卡監控範本')).click()
                editor = page.get_by_role('dialog')
                expect(editor).to_be_visible()
                expect(editor.get_by_label('任務名稱')).to_have_value('RTX 5070 Ti 二手監控')
                SCREENSHOTS.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(SCREENSHOTS / 'shopee-task-editor.png'), full_page=True)
                editor.get_by_role('button', name='取消', exact=True).click()
                expect(editor).not_to_be_visible()
                page.get_by_role('button', name=re.compile('顯示卡監控範本')).click()
                page.keyboard.press('Escape')
                expect(editor).not_to_be_visible()
                page.get_by_role('button', name=re.compile('顯示卡監控範本')).click()
                page.get_by_role('button', name='儲存任務', exact=True).click()
                expect(page.get_by_role('row').filter(has_text='RTX 5070 Ti 二手監控')).to_be_visible()
                page.get_by_role('button', name='執行', exact=True).click()
                page.get_by_role('link', name='商品與推薦', exact=True).click()
                expect(page.get_by_role('heading', name='【模擬】RTX 5070 Ti 16GB 二手顯示卡')).to_be_visible(timeout=15000)
                page.get_by_role('button', name='價格紀錄').click()
                expect(page.get_by_role('heading', name='價格歷史')).to_be_visible()
                expect(page.locator('.price-history strong')).to_have_text('NT$20,000')
                page.keyboard.press('Escape')
                expect(page.get_by_role('dialog')).not_to_be_visible()
                page.get_by_role('link', name='執行紀錄', exact=True).click()
                expect(page.locator('.run-item').first).to_contain_text('執行完成')
                page.get_by_role('link', name='監控任務', exact=True).click()
                page.get_by_role('button', name='編輯RTX 5070 Ti 二手監控', exact=True).click()
                page.get_by_role('dialog').get_by_label('任務名稱').fill('RTX UI 驗證任務')
                page.get_by_role('dialog').get_by_label('最低價格（NT$）').fill('17000')
                page.get_by_role('dialog').get_by_label('最高價格（NT$）').fill('23000')
                page.get_by_role('button', name='儲存任務', exact=True).click()
                expect(page.get_by_role('row').filter(has_text='RTX UI 驗證任務')).to_be_visible()
                page.screenshot(path=str(SCREENSHOTS / 'shopee-dashboard.png'), full_page=True)
                page.get_by_role('link', name='資料來源', exact=True).click()
                expect(page.get_by_role('heading', name='合法商品資料匯入')).to_be_visible()
                page.go_back()
                expect(page.get_by_role('heading', name='監控任務', exact=True)).to_be_visible()
                page.get_by_role('link', name='資料來源', exact=True).click()
                page.get_by_label('商品 JSON', exact=True).fill(json.dumps([{'product_id': 'ui-import-001', 'title': '【測試匯入】Mac mini M4', 'price_twd': 17000, 'description': '合成 UI 測試資料，非真實商品。', 'images': [], 'images_allowed': False}]))
                expect(page.get_by_role('button', name='確認並匯入資料')).to_be_disabled()
                page.get_by_label('我確認有權使用及匯入以上商品資料與圖片').check()
                page.get_by_role('button', name='確認並匯入資料').click()
                expect(page.get_by_text(re.compile('已匯入 1 筆商品'))).to_be_visible()
                page.screenshot(path=str(SCREENSHOTS / 'shopee-sources.png'), full_page=True)
                page.get_by_role('link', name='AI 與通知設定', exact=True).click()
                expect(page.get_by_label('API Base URL')).to_be_enabled()
                page.get_by_label('API Base URL').fill('https://example.invalid/v1')
                page.get_by_label('模型名稱').fill('ui-test-model')
                page.get_by_role('button', name='儲存服務設定').click()
                expect(page.get_by_text('AI 與通知設定已儲存。', exact=True)).to_be_visible()
                expect(page.get_by_label('API Key')).to_have_value('')
                prompt = page.get_by_label('base_prompt.txt', exact=True)
                expect(prompt).to_be_enabled()
                prompt.fill(prompt.input_value() + '\nUI 測試：資訊不足時不得推測。')
                page.get_by_role('button', name='儲存預設提示詞').click()
                expect(page.get_by_text('預設 AI 提示詞已儲存，後續執行將使用新內容。', exact=True)).to_be_visible()
                page.get_by_role('link', name='監控任務', exact=True).click()
                page.once('dialog', lambda dialog: dialog.dismiss())
                page.get_by_role('button', name='刪除RTX UI 驗證任務', exact=True).click()
                expect(page.get_by_role('row').filter(has_text='RTX UI 驗證任務')).to_be_visible()
                page.once('dialog', lambda dialog: dialog.accept())
                page.get_by_role('button', name='刪除RTX UI 驗證任務', exact=True).click()
                expect(page.get_by_text('從第一個監控任務開始')).to_be_visible()
                page.get_by_role('link', name='商品與推薦', exact=True).click()
                expect(page.get_by_role('heading', name='【模擬】RTX 5070 Ti 16GB 二手顯示卡')).to_be_visible()
                page.set_viewport_size({'width': 390, 'height': 844})
                page.get_by_role('link', name='監控任務', exact=True).click()
                page.screenshot(path=str(SCREENSHOTS / 'shopee-mobile.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), '行動版不應有整頁橫向溢出。'
                page.get_by_role('button', name='登出', exact=True).click()
                expect(page.get_by_role('heading', name='登入監控中心')).to_be_visible()
                page.get_by_label('管理員帳號').fill('ui-tester')
                page.get_by_label('密碼', exact=True).fill(password)
                page.get_by_role('button', name='登入', exact=True).click()
                expect(page.get_by_role('heading', name='監控任務', exact=True)).to_be_visible()
                assert not errors, '\n'.join(errors)
                browser.close()
                print('PASS: 登入、取消/Escape、建立、執行、商品、價格歷史、執行紀錄、編輯、返回、匯入授權、設定、提示詞、刪除取消/確認、歷史保留、行動版、登出與再次登入。')
        finally:
            server.terminate()
            server.wait(timeout=10)
            log.close()


if __name__ == '__main__':
    run()
