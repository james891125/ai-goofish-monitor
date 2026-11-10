# 第三方套件與授權聲明

核對日期：2026-11-10。下列版本與授權識別碼取自本次安裝套件的 Python distribution metadata、前端 `package.json` 及套件附帶 LICENSE，不是對所有版本或所有散布方式的法律保證。

## 專案與平台權限分開處理

- 本專案原始 [LICENSE](../LICENSE) 與 [DISCLAIMER.md](../DISCLAIMER.md) 均原文保留。MIT 本文與原免責聲明中的「僅供學習和研究」用途文字有需要釐清之處；若要商用，建議先請原作者釐清。本文件不判斷兩者的法律效力。
- 專案的 MIT 授權不等於取得蝦皮商品、圖片、賣家資料、商標或 API 的使用權，也不代表蝦皮官方核准。
- 第三方程式庫與圖示各自適用自己的授權，不會因為本專案使用 MIT 而自動改授權。
- 再散布時需保留適用的版權、LICENSE 與 NOTICE。Apache-2.0、BSD、ISC 等授權各有條件，請閱讀套件原文。

## Python 直接執行期依賴

來源：`requirements-runtime.txt` 與本次 `.venv` 的套件 metadata。版本區間仍可能在未來安裝時選到不同版本；下表只記錄本次已檢查版本。

| 套件 | 已檢查版本 | metadata 授權 | 套件附帶聲明 |
|---|---|---|---|
| `python-dotenv` | 1.2.4 | BSD-3-Clause | `licenses/LICENSE` |
| `openai` | 3.48.0 | Apache-2.0 | `licenses/LICENSE` |
| `fastapi` | 0.162.2 | MIT | `licenses/LICENSE` |
| `uvicorn` | 0.54.0 | BSD-3-Clause | `licenses/LICENSE.md` |
| `pydantic-settings` | 2.16.2 | MIT | `licenses/LICENSE` |
| `aiofiles` | 25.1.0 | Apache-2.0 | `licenses/LICENSE`、`licenses/NOTICE` |
| `APScheduler` | 3.11.3 | MIT | `licenses/LICENSE.txt` |
| `httpx` | 0.28.1 | BSD-3-Clause | `licenses/LICENSE.md` |
| `tzdata` | 2026.6 | Apache-2.0 | `licenses/LICENSE`、`licenses/licenses/LICENSE_APACHE` |

`uvicorn[standard]` 與 `httpx[socks]` 另會安裝額外依賴；本表不涵蓋其所有間接套件。Python 套件附帶聲明可在安裝環境的 `*.dist-info/licenses/` 查閱，散布整個執行環境時也應保留。

## Python 開發／測試依賴

| 套件 | 已檢查版本 | metadata 授權 |
|---|---|---|
| `pytest` | 9.2.0 | MIT |
| `pytest-asyncio` | 1.4.1.post1 | Apache-2.0 |
| `coverage` | 7.17.2 | Apache-2.0 |

## 前端直接依賴

來源：`web-ui/package.json`、`web-ui/package-lock.json` 與本次 `web-ui/node_modules/<套件>/package.json`。

| 套件 | 已檢查版本 | 套件 metadata 授權 |
|---|---|---|
| `lucide-vue-next` | 0.562.0 | ISC；LICENSE 另保留源自 Feather 部分的 MIT 聲明 |
| `vue` | 3.5.45 | MIT |
| `vue-router` | 4.6.4 | MIT |

## 前端建置／型別檢查依賴

| 套件 | 已檢查版本 | 套件 metadata 授權 |
|---|---|---|
| `@types/node` | 24.10.4 | MIT |
| `@vitejs/plugin-vue` | 6.0.3 | MIT |
| `@vue/tsconfig` | 0.8.1 | MIT |
| `autoprefixer` | 10.4.23 | MIT |
| `postcss` | 8.5.32 | MIT |
| `tailwindcss` | 3.4.17 | MIT |
| `typescript` | 5.9.3 | Apache-2.0 |
| `vite` | 7.3.8 | MIT |
| `vue-tsc` | 3.2.1 | MIT |

## 散布前仍須檢查

1. 本文件是直接依賴清單，不是完整 SBOM 或所有間接套件的法律審核。
2. 重新安裝或升級後，重新核對實際版本、LICENSE 與 NOTICE。
3. 若散布前端打包產物、Docker 映像、整個 Python 環境或安裝包，應檢查實際包含的所有套件、基礎映像及作業系統元件之授權。
4. Dockerfile 會複製專案 LICENSE、原 DISCLAIMER 與本文件；這不代表映像已完成完整授權稽核。
5. 本專案不提供商用適法性、平台資料授權或商標使用的保證；有疑義時請原作者、權利人或合格專業人士釐清。

## 前端執行期套件原始授權文字

以下保留已安裝版本的原文，包含英文法律文字。它們是必要的版權／授權證據，不是舊平台的功能文件。

### lucide-vue-next

來源：`web-ui/node_modules/lucide-vue-next/LICENSE`。

```text
ISC License

Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2023 as part of Feather (MIT). All other copyright (c) for Lucide are held by Lucide Contributors 2025.

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

---

The MIT License (MIT) (for portions derived from Feather)

Copyright (c) 2013-2023 Cole Bemis

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### vue

來源：`web-ui/node_modules/vue/LICENSE`。

```text
The MIT License (MIT)

Copyright (c) 2018-present, Yuxi (Evan) You

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

### vue-router

來源：`web-ui/node_modules/vue-router/LICENSE`。

```text
The MIT License (MIT)

Copyright (c) 2019-present Eduardo San Martin Morote

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
