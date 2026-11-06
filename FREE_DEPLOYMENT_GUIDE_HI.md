# Master Mind Portal — Free Deployment Guide (Hindi)

## चुना गया free setup

- **Application:** Render Free Web Service (FastAPI + HTML/CSS/JS)
- **Database:** Neon Free PostgreSQL
- **Source control / auto deploy:** GitHub branch `security/server-side-migration`
- **Document storage:** अभी बंद। Local disk पर customer documents रखना Render Free पर सुरक्षित नहीं है।

यह hobby/testing deployment है, business-critical production hosting नहीं। Render Free web service 15 मिनट inactivity के बाद sleep हो सकती है; अगली request पर लगभग एक मिनट लग सकता है। Render Free filesystem ephemeral है। Render Free Postgres 30 दिन बाद expire होता है, इसलिए इस project में Render Postgres इस्तेमाल नहीं किया गया। Neon Free database में 1 GB storage और 100 CU-hours/month हैं; compute inactivity के बाद scale-to-zero होता है। Quotas बदल सकती हैं—provider की current pricing/docs हमेशा जाँचें।

Official limits:
- Render: https://render.com/docs/free
- Neon: https://neon.com/docs/introduction/plans
- Neon free quotas: https://neon.com/docs/introduction/plans

## Part A — Neon database बनाना

1. https://neon.tech/ खोलकर GitHub/email से account बनाओ।
2. **Create project** चुनो और Free plan ही रहने दो।
3. Region में Singapore उपलब्ध हो तो चुनो (India से सामान्यतः कम latency)।
4. Project बनने के बाद **Connect** खोलो।
5. PostgreSQL connection string copy करो। इसमें username/password शामिल होते हैं—इसे किसी chat, screenshot या public GitHub file में मत डालना।
6. Connection string में SSL option `sslmode=require` होना चाहिए। इस app का backend `postgres://` और `postgresql://` दोनों URLs को psycopg v3 format में बदलता है।

## Part B — Render Blueprint deploy करना

1. https://render.com/ खोलो और GitHub account connect करो।
2. Private repository `kumarabhishekg/Master-Mind-Portal` को Render GitHub App की access list में allow करो।
3. Render Dashboard → **New** → **Blueprint** खोलो।
4. Repository चुनो और branch `security/server-side-migration` select करो।
5. Render को repository का `render.yaml` पढ़ने दो।
6. Service plan **Free** verify करो। कोई paid plan, instance, add-on या paid database select मत करना।
7. Blueprint जिन environment values को माँगे, उन्हें नीचे दिए अनुसार भरो।

### Required environment variables

| Key | Value |
|---|---|
| `DATABASE_URL` | Neon की पूरी PostgreSQL connection string (secret) |
| `SESSION_SECRET` | Render द्वारा generated value |
| `REQUIRE_EXTERNAL_DATABASE` | `true` |
| `UPLOADS_ENABLED` | `false` |
| `ADMIN_MOBILE` | तुम्हारा 10-digit admin mobile |
| `ADMIN_PASSWORD` | नया, unique, कम-से-कम 14 characters का password |
| `ADMIN_NAME` | Portal Administrator या अपना display name |
| `ALLOWED_ORIGINS` | खाली छोड़ो; app same-origin serve होती है |

**महत्वपूर्ण:** Admin password किसी को मत भेजना और GitHub में मत डालना। पहले से frontend में रहे किसी पुराने password को दोबारा इस्तेमाल मत करना। यदि Render payment card माँगे, रुक जाओ—card details मत भरो; पहले screenshot देखकर free-only route confirm करेंगे।

## Part C — Deployment के बाद checks

1. Render deploy status **Live** होना चाहिए।
2. Render URL खोलो; homepage खुलना चाहिए।
3. `/api/auth/me` बिना login के 401 लौटाए—यह expected है।
4. Signup करके test account बनाओ।
5. उस account से login, dashboard, logout जाँचो।
6. Admin mobile/password से login करके Registered Users देखो।
7. दूसरे normal account से `/admin.html` खोलने पर 403 आना चाहिए।
8. Test accounts के अलावा असली customer data अभी मत डालो।

## अभी क्या चालू नहीं है

- File/document upload बंद है (`UPLOADS_ENABLED=false`)। Render Free का local filesystem persistent नहीं है।
- Aadhaar, PAN, bank statement या कोई भी sensitive customer document इस deployment पर upload मत करना।
- Password reset बंद है क्योंकि email/mobile ownership verification अभी configured नहीं है।
- Free service idle होने पर sleep कर सकती है; इसे 24×7 guaranteed uptime मत समझना।
- Free database/service quotas exceed होने पर app unavailable हो सकती है।

Document upload को चालू करने से पहले private object storage (जैसे Cloudflare R2 या Supabase Storage) integrate करना, private access/signed URLs लगाना, delete/retention flow test करना और billing/payment requirements जाँचना जरूरी है। Cloudflare R2 का free allowance 10 GB-month storage, 1M Class A और 10M Class B operations है, लेकिन account में R2 subscription checkout/billing setup करना पड़ता है; इसलिए बिना billing terms जाँचे इसे auto-enable नहीं करना है.

## Troubleshooting

- **Build fails:** Render Logs में पहली लाल error line देखो; अनुमान से dependencies मत बदलो।
- **Database connection fails:** DATABASE_URL की शुरुआत `postgresql://` या `postgres://` हो; password में special characters URL-encoded हों; SSL enabled हो।
- **Admin login fails:** ADMIN_MOBILE 10 digits हो और ADMIN_PASSWORD कम-से-कम 14 characters; Render environment update के बाद redeploy करो।
- **App sleeps:** Free plan पर expected behavior; पहली request में cold start लगेगा।
- **Uploads return 503:** यह intentional safety lock है, bug नहीं। Persistent private object storage integration के बाद ही enable करना।

## Safety rule

जब तक deploy, signup/login, admin authorization, database persistence और access-control checks pass न हों, website को public customers के लिए announce मत करना। Free hosting का अर्थ zero-cost guarantee या production-grade SLA नहीं है।
