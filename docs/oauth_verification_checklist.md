# Google OAuth 驗證準備清單

## 應用資訊
- [ ] 產品名稱、logo 與網站網域保持一致。
- [ ] 隱私權政策：`/legal/privacy_policy.md`（部署於公開網址）。
- [ ] 服務條款：`/legal/terms_of_service.md`（部署於公開網址）。
- [ ] 提供測試帳號（至少 2 組，可登入並執行完整流程）。
- [ ] 提供示範影片：登入 → 上傳名片 → 審核 → 同步至 Google 通訊錄 → 下載 CSV。

## 授權範圍
- [ ] 僅申請 `https://www.googleapis.com/auth/contacts` 或 `contacts.readonly`。
- [ ] 說明為何需要該權限（同步名片資訊至聯絡人）。
- [ ] 若額外申請 `openid,email,profile`，需說明用於識別使用者帳號。

## 資料使用說明
- [ ] 描述哪些資料會被蒐集：名片影像、OCR 結果、聯絡人欄位、Stripe 付款資訊。
- [ ] 說明保留時間與刪除機制（預設 24 小時、可立即刪除）。
- [ ] 提供資料刪除管道（介面操作＋客服信箱）。

## 安全性
- [ ] 全站使用 HTTPS（正式環境）。
- [ ] OAuth 回呼網址與 Google Cloud Console 設定一致。
- [ ] Access token/refresh token 安全儲存並限制權限。

## 測試範例
- [ ] 至少 5 組名片照片與預期輸出。
- [ ] 說明去重策略與可能的例外（Email/手機相同但姓名不同 → 視為新聯絡人）。
- [ ] 付款流程示範（測試 Stripe 帳號）。

## 文件與截圖
- [ ] 首頁、審核頁、結果頁截圖。
- [ ] Google 通訊錄寫入成功的截圖（顯示名稱、電話、Email、照片）。
- [ ] 線上說明文件或 FAQ（可放在 README 或獨立頁面）。

