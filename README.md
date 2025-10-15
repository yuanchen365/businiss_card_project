# 名片辨識 × Google 通訊錄 (FastAPI)

一個可以上傳名片影像、進行 OCR 解析，並同步至 Google People API 的示範專案。

- Google OAuth 2.0 登入（預設 scope：contacts + openid + userinfo.email）。
- 多檔上傳、排序、略過、草稿儲存等友善審核介面。
- 去重策略：Email / 手機 / 姓名 + 公司皆相符才會更新，避免錯誤合併。
- 同步至 Google 通訊錄時會處理 `etag` 並上傳名片照片。
- 收費模式：每位新使用者可免費試用 5 張名片額度，並可購買 5 美元倍數的點數包（50、100、150 張）。
- 內建 Dockerfile、Cloud Run 部署腳本、Stripe Checkout Webhook 範例。

## 專案結構

```
project/
  main.py
  services/
    billing.py
    ...
  templates/
    billing.html
    ...
  static/
    styles.css
  scripts/
    deploy_cloud_run.sh
    check_env.py
  tests/
    ... (15 項單元測試)
  data/  # 儲存額度資訊（執行時產生，勿提交）
```

## 主要環境變數 (.env)

| 變數 | 說明 |
| --- | --- |
| `SECRET_KEY` | FastAPI Session 加密金鑰 |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth Web 用戶端憑證 |
| `GOOGLE_REDIRECT_URI` | 例：`http://localhost:8000/auth/callback` |
| `GOOGLE_SCOPES` | 預設 `https://www.googleapis.com/auth/contacts,openid,https://www.googleapis.com/auth/userinfo.email` |
| `VISION_API_KEY` | Cloud Vision API 金鑰（可留空改用 Tesseract） |
| `OCR_FALLBACK` | `tesseract` 或 `none` |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | Stripe API 金鑰與 Webhook 簽章 |
| `STRIPE_PRICE_CREDITS` / `STRIPE_PRICE_CREDITS_1` / `STRIPE_PRICE_CREDITS_2` | 各點數包的 Stripe Price ID（依序對應 50 / 100 / 150 張） |
| `CREDIT_PACK_TIERS` | 點數包清單，格式 `名片張數:價格`，預設 `50:5,100:10,150:15` |
| `CREDIT_PACK_PRICE` | 預設價格（當未設定 tiers 時使用） |

## 安裝與啟動

```bash
python -m venv venv
venv\Scriptsctivate
pip install -r requirements.txt
copy .env.example .env  # 填入 Google 與 Stripe 金鑰
uvicorn main:app --reload --port 8000
```

造訪 `http://localhost:8000/`，登入 Google 後即可上傳名片 → 審核 → 寫入 Google 通訊錄。結果頁提供 CSV 日誌與聯絡人照片同步狀態。

## Stripe 點數流程

- 每個帳號預設擁有 5 張免費額度。
- `/billing` 頁面可選擇 5/10/15 美元的點數包；完成 Stripe Checkout 後，Webhook (`/stripe/webhook`) 會依 tier 增加對應張數並記錄歷史。
- 每次成功寫入或更新聯絡人扣 1 張額度；略過或完全相同則不扣。

## 其他

- `services/billing.py` 負責額度管理、歷史紀錄與免費試用邏輯。
- `templates/billing.html` 提供中文化的方案頁面。
- `scripts/check_env.py` 可快速檢查環境變數是否設定。
- 單元測試使用 `pytest -q`。
