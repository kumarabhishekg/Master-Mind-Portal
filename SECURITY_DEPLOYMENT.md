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
