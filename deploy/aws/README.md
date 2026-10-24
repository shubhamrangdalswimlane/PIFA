# Deploy PIFA on AWS (one server)

Everything runs on **one EC2 server** with Docker: Caddy (HTTPS + web app), the API, Keycloak, the file service, SFTP and PostgreSQL.
Only ports 80/443 are open to the internet. Estimated cost: **about $1.2 per day** (t3.medium) while it is running.

Files in this folder: `docker-compose.aws.yml` (all services), `Dockerfile.api`, `Dockerfile.web`, `Caddyfile`, `setup.sh` (writes `.env`).
This setup was tested end to end (all 42 checks of the full planning cycle through HTTPS) on a local copy; the AWS steps below follow the same path.

## 1. Create the server (AWS Console)

1. Choose a region near you (top right), e.g. **N. Virginia** or **Mumbai (ap-south-1)**.
2. **EC2 → Key pairs → Create key pair** → name `pifa`, type RSA, format `.pem`. Save the downloaded file.
3. **EC2 → Security Groups → Create security group**: name `pifa-sg`, add **inbound rules**:

   | Type | Port | Source |
   |---|---|---|
   | SSH | 22 | **My IP** (not Anywhere) |
   | HTTP | 80 | Anywhere (0.0.0.0/0) |
   | HTTPS | 443 | Anywhere (0.0.0.0/0) |

4. **EC2 → Elastic IPs → Allocate Elastic IP address** → Allocate. (A fixed address: the web addresses and Keycloak's settings depend on it. It is free while attached to a running server.)
5. **EC2 → Launch instance**:
   - Name `pifa`, Image **Ubuntu Server 24.04 LTS**, Instance type **t3.medium** (4 GB; the whole stack uses under 1 GB)
   - Key pair `pifa`, Security group `pifa-sg`
   - Storage **30 GiB gp3**
6. When it is running: **Elastic IPs → select yours → Actions → Associate Elastic IP address** → pick the `pifa` instance. Note this IP (example `3.12.34.56`).

## 2. Install Docker on the server

From your computer (replace the IP and the key path):

```bash
ssh -i pifa.pem ubuntu@3.12.34.56
```

On the server:

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
sudo usermod -aG docker ubuntu && newgrp docker
```

## 3. Get the code and generate the settings

```bash
git clone https://github.com/shubhamrangdalswimlane/PIFA.git
cd PIFA/deploy/aws
./setup.sh
```

(If the repository is private, clone with a GitHub personal access token: `git clone https://<token>@github.com/shubhamrangdalswimlane/PIFA.git`.)

`setup.sh` finds the server's public IP, builds free host names from it (`app.3-12-34-56.sslip.io` and `auth.3-12-34-56.sslip.io`),
creates random secrets and the SFTP key pair, and writes `.env`. **It prints two passwords once: copy them now** (the password of all 11 PIFA users, and Keycloak's admin password).

Own domain instead of `sslip.io`: create two DNS **A records** pointing to the Elastic IP (e.g. `pifa.example.com` and `auth.example.com`), then run
`APP_HOST=pifa.example.com AUTH_HOST=auth.example.com ./setup.sh`.

## 4. Start everything

```bash
docker compose -f docker-compose.aws.yml up -d --build
```

The first build takes about 5–8 minutes (Keycloak, the web build, Python packages). Watch it with `docker compose -f docker-compose.aws.yml logs -f keycloak`
until you see `Keycloak 26.4 … started`. Caddy requests the HTTPS certificates automatically on the first visit.

## 5. Use it

1. Open `https://app.<your-ip-with-dashes>.sslip.io` (the address `setup.sh` printed).
2. Sign in as `admin` with the **user password** it printed (other users: `sm.north`, `sm.east`, `sm.west`, `sm.south`, `rm.north` … `rm.south`, `planner`, `head`).
3. **Admin → Health**: all six services should be green.
4. Upload the sample files from `data_synthetic/` as the Sales Managers, and continue the cycle.

Keycloak's admin console: `https://auth.<…>.sslip.io/admin`, user `kcadmin`, with the Keycloak admin password.

## Operating it

| Task | Command (in `PIFA/deploy/aws`) |
|---|---|
| Status | `docker compose -f docker-compose.aws.yml ps` |
| Logs of one service | `docker compose -f docker-compose.aws.yml logs -f api` (also `keycloak`, `files`, `web`) |
| Update to new code | `git pull && docker compose -f docker-compose.aws.yml up -d --build` |
| Stop (keeps data) | `docker compose -f docker-compose.aws.yml stop` |

Data lives in Docker volumes on the server's disk (`pgdata`, `sftpdata`). There are no automatic backups: for anything beyond a demo, take EBS snapshots.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Browser says the certificate is invalid, or Caddy logs "challenge failed" | Ports 80/443 not open in `pifa-sg`, or the Elastic IP is not attached. `sslip.io` is a shared free domain and Let's Encrypt can rate-limit it; use your own domain if it keeps failing. |
| "Invalid parameter: redirect_uri" at sign-in | The server's IP changed after the first start (no Elastic IP). Keycloak keeps the first addresses; recreate with `docker compose -f docker-compose.aws.yml down -v`, delete `.env`, run `./setup.sh`, and start again. |
| Sign-in page loads but the app shows errors | `docker compose -f docker-compose.aws.yml logs api` — usually the database or Keycloak is still starting; wait a minute. |
| Out of memory while building | Use t3.medium or larger, or add 2 GB swap. |

## Take it down (stop paying)

1. **EC2 → Instances → select `pifa` → Instance state → Terminate** (this also deletes its disk).
2. **EC2 → Elastic IPs → select the IP → Actions → Release Elastic IP addresses** (an unattached Elastic IP is billed).
3. Optional: delete the security group `pifa-sg` and the key pair `pifa`.
4. Check **Billing → Bills** the next day to confirm nothing is still running.

## Approximate cost (US East, on demand; check the AWS Pricing Calculator)

| Item | Per day |
|---|---|
| t3.medium server | ~$1.00 |
| 30 GB gp3 disk | ~$0.08 |
| Public IPv4 address (Elastic IP) | ~$0.12 |
| Data transfer (first 100 GB/month free) | ~$0 |
| **Total** | **≈ $1.2** (about $36 a month if left on) |
