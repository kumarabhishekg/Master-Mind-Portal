# Secure deployment checklist

This backend expects the HTML pages and FastAPI API to be served from the same HTTPS origin.

## Required production environment variables

- `SESSION_SECRET`: a new, random secret with at least 32 bytes of entropy. Never commit it.
- `ADMIN_MOBILE`: the administrator's 10-digit mobile number.
- `ADMIN_PASSWORD`: a unique password with at least 14 characters. Do not reuse an old password.
- `DATABASE_URL`: use a managed production database URL; SQLite is intended only for local development or a single persistent instance.
- `UPLOAD_DIR`: a private, persistent directory or mounted volume for uploaded files.
- `ALLOWED_ORIGINS`: leave empty for same-origin hosting. If a separate frontend origin is unavoidable, list exact HTTPS origins only.

The example values in `.env.example` are placeholders and must never be used as production credentials.

## Important deployment requirements

1. Enable HTTPS. The authentication cookie is Secure and will not be sent over plain HTTP.
2. Keep the database and upload directory outside the public web root. Do not serve them as static files.
3. Back up the database and uploaded files together, and test restoration.
4. Restrict access to production environment variables and database credentials.
5. Configure a persistent disk or private object storage for uploads. Ephemeral application filesystems can lose customer documents during redeploys.
6. Rotate any admin credentials that were ever committed to Git history.
7. Password reset remains intentionally disabled until a real OTP/email ownership-verification flow is implemented.
8. Review repository history for previously committed database files, customer uploads, or credentials. Removing a file in a later commit does not erase earlier Git history.

## Local development

Because the session cookie is Secure, test authentication through HTTPS. Do not disable Secure cookies in production to make plain-HTTP testing work.

## Temporary free-hosting mode (testing only)

The Render Blueprint is configured for the Free web-service plan. This is a demonstration environment, not production hosting.

- The service sleeps after 15 minutes without traffic and can take about a minute to wake.
- Its filesystem is ephemeral. The SQLite database and any local files can disappear on restart, redeploy, or spin-down. User accounts and service requests must be treated as disposable test data.
- File uploads and admin document issuance are deliberately disabled when `UPLOADS_ENABLED=false`. Do not enable them on this plan: uploaded customer documents would be lost and must not be entrusted to ephemeral storage.
- Do not collect Aadhaar, PAN, banking documents, or other real customer personal data on this deployment.
- Render's free Postgres is not a permanent workaround: Render documents a 30-day expiry, no backups, and a 1 GB limit.
- Before real customers use the portal, move to a paid persistent service and private persistent object storage, configure a durable managed database with backups, enable uploads only after verifying access controls, and test restore procedures.

The free blueprint sets `UPLOADS_ENABLED=false` and uses SQLite only for temporary demonstrations. A restart or spin-down may reset the database.


## Free Render preview mode

The free Render web service has an ephemeral filesystem and sleeps after 15 minutes without traffic. Do not store SQLite data or customer documents on it. The free blueprint therefore requires an externally hosted PostgreSQL connection string via `DATABASE_URL`; startup deliberately fails if this is missing or points to SQLite. Configure the external database before deploying.

Customer document upload, issued-document upload, and file download endpoints are disabled by `UPLOADS_ENABLED=false`. This is intentional: the current backend writes files to local disk, which is lost on Render free restarts/redeploys. Do not enable uploads until a private object-storage adapter (for example, a private Supabase Storage bucket with server-side authorization) is implemented and tested. Never use public buckets for Aadhaar/PAN or other identity documents.

Supabase Free currently advertises 500 MB database, 1 GB storage, 5 GB egress and pauses projects after one week of inactivity. These are prototype limits, not a production backup/retention guarantee. Monitor quotas and keep independent backups.