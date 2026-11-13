# Master Mind Portal — Google Cloud Setup (Hindi)

इस ZIP में Frontend और FastAPI Backend का code तैयार है। Google Cloud/AWS account के अंदर resources बनाने के लिए नीचे के account-side steps जरूरी हैं। कोई भी private key इस ZIP या GitHub में मत डालना।

## A. Google Cloud में एक बार का setup

1. https://console.cloud.google.com/ खोलो और अपना project चुनो।
2. APIs & Services में **Cloud Firestore API** और **Google Drive API** enable करो।
3. Firestore खोलो → Create database → **Native mode** चुनो → location चुनकर database बनाओ।
4. IAM & Admin → Service Accounts → Create Service Account। नाम रखो `master-mind-backend`।
5. इस service account को project पर **Cloud Datastore User** role दो।
6. Service Account → Keys में जाकर नई JSON key बनाओ। लेकिन पहले chat में upload की गई पुरानी key को Delete/Revoke करना अनिवार्य है। पुरानी key compromised है।
7. Google Drive में `Master Mind Customer Documents` नाम का folder बनाओ। Folder को service-account email के साथ **Editor** access में share करो। Link sharing / public access enable मत करना।
8. Drive URL में `/folders/` के बाद वाला ID नोट कर लो।

## B. AWS EC2 पर files रखना

ZIP को EC2 पर extract करके project folder का नाम `Master-Mind-Portal` रखो। SSH terminal में:

```bash
cd ~/Master-Mind-Portal
mkdir -p secrets
chmod 700 secrets
```

नई JSON key को सुरक्षित तरीके से इस path पर upload करो:

```text
/home/ubuntu/Master-Mind-Portal/secrets/google-service-account.json
```

फिर:

```bash
chmod 600 ~/Master-Mind-Portal/secrets/google-service-account.json
cp .env.example .env
nano .env
```

`.env` में values भरो:

```env
GOOGLE_CLOUD_PROJECT=Google_Cloud_Project_ID
GOOGLE_APPLICATION_CREDENTIALS=/home/ubuntu/Master-Mind-Portal/secrets/google-service-account.json
GOOGLE_DRIVE_FOLDER_ID=Drive_Folder_ID
SESSION_SECRET=Random_Secret
ADMIN_MOBILE=Apna_10_Digit_Admin_Mobile
ADMIN_PASSWORD=Apna_Strong_Password_12_Characters_Or_More
ADMIN_NAME=Master Mind Administrator
ADMIN_EMAIL=Apna_Email
COOKIE_SECURE=true
CORS_ORIGINS=
```

Random session secret बनाने के लिए:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

उस output को `SESSION_SECRET` में डालो। `ADMIN_PASSWORD` के लिए नया और अलग password रखो। `.env` या JSON key को GitHub पर कभी push मत करना।

## C. Backend install और start

Project folder में:

```bash
cd ~/Master-Mind-Portal
bash scripts/deploy_ec2.sh
```

यह script virtual environment बनाएगी, requirements install करेगी और `mastermind-portal` नाम की systemd service बनाएगी। Service केवल `127.0.0.1:8000` पर चलेगी।

Status:

```bash
sudo systemctl status mastermind-portal
sudo journalctl -u mastermind-portal -n 100 --no-pager
```

## D. Website पर HTTPS लगाना

`deploy/nginx-mastermind.conf` में `YOUR_DOMAIN` को अपने domain से बदलो। फिर:

```bash
sudo apt update
sudo apt install -y nginx
sudo cp deploy/nginx-mastermind.conf /etc/nginx/sites-available/mastermind
sudo nano /etc/nginx/sites-available/mastermind
sudo ln -s /etc/nginx/sites-available/mastermind /etc/nginx/sites-enabled/mastermind
sudo nginx -t
sudo systemctl reload nginx
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d YOUR_DOMAIN -d www.YOUR_DOMAIN
```

Domain का DNS record EC2 के public IP पर point होना चाहिए। AWS Security Group में केवल ports **80** और **443** public रखो; port **8000** public मत खोलना। HTTPS चालू होने के बाद `.env` में `COOKIE_SECURE=true` रखो और service restart करो:

```bash
sudo systemctl restart mastermind-portal
```

## E. Final test

Browser में `https://YOUR_DOMAIN/api/health` खोलो। सही response में ये होना चाहिए:

- `status`: `ok`
- `database`: `google-cloud-firestore`
- `storage`: `google-drive`

फिर customer signup/login, application submit, private document view, दूसरे user से access-denied, Admin login, user block/unblock, application status, print queue और issued document upload/download जाँचो। जब तक ये tests pass न हों, पुरानी live website को replace मत करना।

## क्या इस ZIP से अपने-आप नहीं हो सकता

तुम्हारे Google Cloud/AWS account में login किए बिना मैं Firestore database create, IAM role assign, Drive folder share, key revoke, AWS files copy, domain DNS या HTTPS certificate issue नहीं कर सकता। ये account-level permissions हैं। इस ZIP में code, configuration template, deployment script और steps तैयार हैं; live connection का दावा तब ही सही होगा जब ऊपर का health check और browser tests pass हों।
