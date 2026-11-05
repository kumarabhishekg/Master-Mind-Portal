# Render service configuration

Set these values in the Render web service's Environment settings before deploying:

- `DATABASE_URL`: Internal connection string for the Render Postgres database. The app uses it for accounts, application submissions, and uploaded file bytes.
- `PORTAL_AUTH_SECRET`: A private random value with at least 32 bytes of entropy. Keep it stable across deploys so active sessions stay valid.
- `ADMIN_MOBILE_1` and `ADMIN_PASSWORD_1`: First administrator login. Set the password as a Render secret and rotate credentials that were previously stored in frontend code.
- `ADMIN_MOBILE_2` and `ADMIN_PASSWORD_2`: Optional second administrator login.

Do not commit the values of these variables to GitHub. The app falls back to SQLite for local development, but Render's local filesystem is ephemeral; a persistent Postgres `DATABASE_URL` is required for production data to survive restarts and deploys.
