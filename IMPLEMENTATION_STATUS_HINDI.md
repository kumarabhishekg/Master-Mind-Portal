# Master Mind Portal — Implementation Status (13 Nov 2026)

## Code changes in this build
- Neon, PostgreSQL, SQLAlchemy, psycopg and local SQLite dependencies/configuration are absent.
- Firestore is the only configured database. Google Drive is private document storage only.
- Signup/login/logout/current-user use server-side session cookies and bcrypt password hashes.
- Admin bootstrap, user listing, block/unblock and delete APIs are present.
- Customer service application records are submitted to Firestore.
- Customer uploads go to Drive; Firestore stores metadata and owner association. File access checks owner/admin.
- Public inquiry form writes to Firestore without creating a customer login.
- Instant Print Queue records are stored in Firestore; Admin can update/delete and open the print editor by cloud record ID.
- Issued documents use a separate Firestore collection and private Drive files; customer access is restricted to the target mobile account.
- HTML pages in this build no longer use localStorage/sessionStorage or base64 FileReader fallbacks for portal records.
- Service account JSON, `.env`, private keys and uploaded customer documents are excluded from the ZIP.

## Validation performed locally
- Python source compiles with `compileall`.
- All inline JavaScript blocks in HTML pages pass `node --check`.
- Grep check finds no `localStorage`, `sessionStorage` or `FileReader` references in HTML.
- ZIP contents must still be inspected before publishing; no live Google Cloud/AWS credentials are included.

## Not possible to verify from this workspace
- Firestore project/database creation and IAM permissions.
- Drive API enablement, folder sharing and upload/download permissions.
- Real account signup/login, browser sessions, user isolation, Drive uploads, admin actions and print workflow against your Google Cloud project.
- AWS EC2 deployment, DNS and HTTPS.

## Required before production
1. Revoke the service-account private key that was uploaded in chat; create a new key and keep it only on the server.
2. Create Firestore Native database; enable Firestore and Drive APIs.
3. Share the private Drive folder with the backend service account.
4. Configure `.env`, install dependencies and run behind HTTPS on AWS.
5. Pass every acceptance test in `README_DEPLOY_HINDI.md`.
6. Export/migrate old browser-local and Neon records separately if they must be retained.
