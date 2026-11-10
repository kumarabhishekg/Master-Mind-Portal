# Secure deployment checklist

This backend expects the HTML pages and FastAPI API to be served from the same HTTPS origin.

## Required production environment variables

- `SESSION_SECRET`: a new, random secret with at least 32 bytes of entropy. Never commit it.
- `ADMIN_MOBILE`: the administrator's 10-digit mobile number.
- `ADMIN_PASSWORD`: a unique password with at least 14 characters. Do not reuse an old password.
- `DATABASE_URL`: use a managed production database URL; SQLite is intended only for local development or a single persistent instance.
- `MONGODB_URI` and `MONGODB_DATABASE`: MongoDB Atlas connection and database for signup/login accounts. Keep the URI only in the server environment.
- `MONGO_AUTH_REQUIRED=true`: enables MongoDB as the required source of truth for accounts. Do not enable until Atlas is reachable from the EC2 instance.
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

## MongoDB Atlas account storage

When `MONGODB_URI` is set, the `users` collection in `MONGODB_DATABASE` becomes the source of truth for account signup, login, roles, and blocked status. Existing SQL `users` rows are copied into MongoDB without replacing documents that already exist there. The legacy SQL rows are retained as a rollback copy; new account writes go to MongoDB. Passwords are stored as scrypt hashes.

The existing SQL database continues to store service requests, uploaded-file metadata, print queue entries, and issued-document metadata. This keeps the planned Google datastore separate until that integration is explicitly implemented.

In Atlas, create a database user with read/write access to the portal database and allow the EC2 instance's public egress IP as a `/32` network access entry. Do not use `0.0.0.0/0`. Put the resulting URI in `/home/ubuntu/Master-Mind-Portal/.env`, set `MONGODB_DATABASE=mastermind_portal` and `MONGO_AUTH_REQUIRED=true`, and restrict the file with `chmod 600 .env`. Do not paste the URI into chat or commit it.

## Ubuntu EC2 service

The repository includes `deploy/mastermind-portal.service` and `deploy/nginx-mastermind.conf.example`. The service runs FastAPI on loopback port 8000; Nginx must proxy the HTTPS site to it. The example Nginx configuration requires a real domain and an installed TLS certificate. Do not use the current static-only `/var/www/html` configuration with this API-backed login: signup, login, session cookies, and protected pages require FastAPI and HTTPS.

Install the service file at `/etc/systemd/system/mastermind-portal.service`, ensure the `.env` contains the required session/admin values and MongoDB values, then run `sudo systemctl daemon-reload` and `sudo systemctl enable --now mastermind-portal`. Verify with `sudo systemctl status mastermind-portal --no-pager` and `curl -fsS http://127.0.0.1:8000/api/auth/me` (401 is expected when not logged in). Configure the domain's HTTPS Nginx reverse proxy only after replacing the example domain and certificate paths, then run `sudo nginx -t` and reload Nginx.

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
