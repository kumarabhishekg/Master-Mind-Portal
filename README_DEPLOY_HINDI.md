# Master Mind Portal — Google Cloud + AWS Deployment

## Architecture
- Frontend: existing HTML/CSS/JavaScript pages served by FastAPI.
- Backend: FastAPI (`main.py`).
- Database: Google Cloud Firestore in Native mode.
- Private file storage: Google Drive folder shared only with the backend service account.
- Authentication: server-side signed session cookie; bcrypt password hashes stored in Firestore.
- Neon/PostgreSQL/SQLite are not used. Browser `localStorage` is not used for portal records.

## 1. Google Cloud setup
1. Open https://console.cloud.google.com/ and select the project.
2. Enable **Cloud Firestore API** and **Google Drive API**.
3. Open Firestore and create a database in **Native mode**. Choose a location close to your users; the location cannot be changed later.
4. In IAM & Admin → Service Accounts, create a backend-only service account.
5. Grant the service account **Cloud Datastore User** (Firestore read/write) on the project.
6. In Google Drive, create a folder for customer documents. Share that folder with the service account email as **Editor**. Do not make the folder public.
7. Copy the folder ID from the folder URL. It is the text after `/folders/`.
8. The service account needs Drive access to that shared folder. The backend keeps uploaded files private and serves them only after checking the logged-in owner or admin.

### Critical credential rotation
The service-account JSON key previously uploaded in this chat must be revoked/deleted in IAM → Service Accounts → Keys. It was exposed. Create a new key only after revoking the old one. Never put the new JSON in the ZIP, HTML, GitHub, or chat.

## 2. Put credentials on the AWS server
On EC2, create a private folder and copy the newly generated JSON key directly to the server using a secure method:
```bash
mkdir -p ~/Master-Mind-Portal/secrets
chmod 700 ~/Master-Mind-Portal/secrets
chmod 600 ~/Master-Mind-Portal/secrets/google-service-account.json
```
Set `GOOGLE_APPLICATION_CREDENTIALS` to that exact server path. Do not upload the key into the Git repository.

## 3. Environment variables
Create `.env` beside `main.py` (never commit it):
```env
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
GOOGLE_APPLICATION_CREDENTIALS=/home/ubuntu/Master-Mind-Portal/secrets/google-service-account.json
GOOGLE_DRIVE_FOLDER_ID=YOUR_PRIVATE_DRIVE_FOLDER_ID
SESSION_SECRET=GENERATE_A_RANDOM_SECRET_AT_LEAST_32_CHARACTERS
ADMIN_MOBILE=YOUR_10_DIGIT_ADMIN_MOBILE
ADMIN_PASSWORD=YOUR_STRONG_ADMIN_PASSWORD_AT_LEAST_12_CHARACTERS
ADMIN_NAME=Master Mind Administrator
ADMIN_EMAIL=YOUR_ADMIN_EMAIL
COOKIE_SECURE=true
CORS_ORIGINS=
```
Generate a session secret on the server with:
```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```
Use the output as `SESSION_SECRET`. Use a unique admin password. Do not use the example values.

## 4. Install and run on EC2
Use Python 3.12 or newer supported by the pinned dependencies. First copy `.env.example` to `.env`, set the real values, and make sure the new Google key file is at the path configured in `GOOGLE_APPLICATION_CREDENTIALS`. From the project folder:
```bash
cp .env.example .env
nano .env
bash scripts/deploy_ec2.sh
```
The script creates the virtual environment, installs dependencies and registers a systemd service listening only on `127.0.0.1:8000`. It does not replace Nginx or create HTTPS.

Configure Nginx:
```bash
sudo apt update && sudo apt install -y nginx
sudo cp deploy/nginx-mastermind.conf /etc/nginx/sites-available/mastermind
sudo nano /etc/nginx/sites-available/mastermind   # replace YOUR_DOMAIN
sudo ln -s /etc/nginx/sites-available/mastermind /etc/nginx/sites-enabled/mastermind
sudo nginx -t && sudo systemctl reload nginx
```
Then install Certbot and issue a certificate for your real domain (the domain must point to the EC2 public IP):
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d YOUR_DOMAIN -d www.YOUR_DOMAIN
```
Keep port 8000 private in the EC2 security group; expose only ports 80 and 443. Use `COOKIE_SECURE=true` only after HTTPS works. Check logs with `sudo journalctl -u mastermind-portal -n 100 --no-pager`.

## 5. Health check and acceptance tests
Open `https://YOUR_DOMAIN/api/health`. A successful result must show:
- `status: ok`
- `database: google-cloud-firestore`
- `storage: google-drive`

Then test in a browser:
1. Create a normal customer account and log in.
2. Submit one service request with a PDF/image; verify it appears in Admin → Applications.
3. Open the file while logged in as its owner.
4. Log in as a different customer and confirm the first customer's file is inaccessible.
5. Log in as admin; verify users, block/unblock, application status, delete, print queue and issued-document upload.
6. Log in as the target customer and open the issued document.
7. Test logout and confirm protected pages redirect to login.

## Important limitations
- This ZIP contains code and setup instructions, not your Google Cloud credentials, database, Drive folder, AWS login or domain. I cannot create resources inside your Google Cloud/AWS accounts from this ZIP alone.
- Existing browser localStorage data and old Neon records are not automatically imported. Export them from the old browser/database before switching if you need them.
- The service-account JSON key previously shared must be revoked. This ZIP intentionally contains no service-account JSON or `.env`.
- A syntax check is not a live integration test. Do not put the site into production until `/api/health` and the acceptance tests above pass.
