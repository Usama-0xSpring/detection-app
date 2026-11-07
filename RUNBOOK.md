# Detection App: Local to Azure with CI/CD (Step-by-Step Runbook)

A small React + FastAPI + YOLOv8n app that runs on an Azure VM and redeploys itself on every push to GitHub. The model is fetched from Azure Blob Storage and verified by checksum.

Placeholders used below: `<VM_IP>` (the VM's public IP) and `<github-user>` (your GitHub username). Never paste secrets (private key, SAS URL) into chat, code or Git.

## Contents

1. [Overview](#1-overview)
2. [Prerequisites and cost safety](#2-prerequisites-and-cost-safety)
3. [Build the app locally](#3-build-the-app-locally)
4. [Model download at startup](#4-model-download-at-startup)
5. [Docker and Compose](#5-docker-and-compose)
6. [GitHub repository](#6-github-repository)
7. [CI/CD pipeline with GitHub Actions](#7-cicd-pipeline-with-github-actions)
8. [Azure setup: Blob storage and the model](#8-azure-setup-blob-storage-and-the-model)
9. [Azure VM: create, SSH key, Docker](#9-azure-vm-create-ssh-key-docker)
10. [GitHub secrets, first deploy, verification](#10-github-secrets-first-deploy-verification)
11. [Troubleshooting](#11-troubleshooting)
12. [Cleanup, cost control and next steps](#12-cleanup-cost-control-and-next-steps)

---

## 1. Overview

| Part | Choice | Why |
| --- | --- | --- |
| Frontend | React (Vite), served by nginx | Small static build |
| Backend | FastAPI + onnxruntime (CPU) | No GPU or PyTorch needed at runtime |
| Model | YOLOv8n exported to ONNX (12.8 MB) | Small, public, replaceable by your own signature model |
| Model storage | Azure Blob Storage + read-only SAS URL | Keeps weights out of Git and Docker images |
| Containers | Docker + Docker Compose | Same setup locally and on the VM |
| Registry | GitHub Container Registry (GHCR) | Free; Azure Container Registry is not |
| CI/CD | GitHub Actions | Free for public repos, no extra account |
| Host | One Azure VM (Ubuntu, 2 vCPU, 4 GiB) | Teaches SSH and Docker on a real server |

The pipeline, end to end:

1. Push to `main`.
2. GitHub Actions runs the backend tests and the frontend build.
3. It builds both Docker images and smoke-tests them with Docker Compose.
4. It pushes the images to GHCR, tagged with the commit SHA.
5. It connects to the VM over SSH, pulls the new images and restarts them.
6. The backend downloads the model from Blob (first start only) and checks its SHA256.
7. The deploy job passes only when `/api/health` reports `model_loaded: true`.

---

## 2. Prerequisites and cost safety

You need five tools and two accounts. The rule that keeps the bill at zero: never upgrade the Azure trial.

| Need | Version | Install (Windows) |
| --- | --- | --- |
| Python | 3.11 | `winget install -e --id Python.Python.3.11` |
| Node.js | 20 LTS or newer | `winget install -e --id OpenJS.NodeJS.LTS` |
| Git | any recent | `winget install -e --id Git.Git` |
| Docker Desktop | running | docker.com, then `docker --version` |
| Azure CLI (optional) | any | `winget install -e --id Microsoft.AzureCLI` |
| GitHub account | free | github.com |
| Azure account | free trial or Azure for Students | azure.microsoft.com/free |

Open a new terminal after installing so the new PATH applies.

Cost rules:

- Azure free trial: $200 credit for 30 days. When it ends, resources stop; nothing is charged unless you click **Upgrade**.
- Azure for Students: about $100 credit, no card; check which VM sizes and regions it allows before the session.
- Create one budget (Cost Management, Budgets): amount 5, alerts at 20% (about $1) and 100% ($5). Budgets only send email; they do not stop spending, and data lags up to a day.
- Put everything in one resource group (`rg-demo`) so one delete removes it all.
- A stopped VM still bills for compute; a deallocated VM bills only disk and IP; deleting the resource group bills nothing.

---

## 3. Build the app locally

Build and test everything on your own machine first. The backend and frontend run as two processes, and the model runs on CPU through onnxruntime.

```
detection-app/
├─ backend/       FastAPI + onnxruntime: main.py, detector.py, model_store.py, export_model.py, tests/
├─ frontend/      React + Vite: src/App.jsx
├─ test-images/   sample photos (kept out of Git)
├─ docker-compose.yml, docker-compose.prod.yml, docker-compose.local-model.yml
└─ .github/workflows/ci.yml
```

**Backend** (terminal 1). Calling the venv's Python directly (`.venv\Scripts\python.exe -m ...`) avoids broken launchers if you ever rename the folder.

```powershell
cd detection-app\backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-export.txt   # one-time, large (PyTorch)
.venv\Scripts\python.exe export_model.py                               # creates models\model.onnx + labels.txt
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

Check `http://localhost:8000/health` (expect `"model_loaded":true`) and `http://localhost:8000/docs`.

**Frontend** (terminal 2):

```powershell
cd detection-app\frontend
npm install
npm run dev
```

Open `http://localhost:5173`, upload a photo and click **Detect**; boxes and labels appear over the image.

How the model is used:

- `export_model.py` downloads pretrained `yolov8n.pt` (COCO: 80 everyday objects, not signatures) and exports `models/model.onnx` plus `models/labels.txt`. PyTorch is needed only for this one step.
- On startup `main.py` creates a `Detector` (`detector.py`), which opens the ONNX file with onnxruntime. Each upload is resized to 640x640, run through the model, filtered by confidence and overlap, and mapped back to original pixels.
- To use your own model later: `python export_model.py path\to\best.pt`. No code changes.
- Delete the leftover `backend\yolov8n.pt` and `backend\yolov8n.onnx` after exporting; only `models\model.onnx` is used.
- Stop the app: close both terminals. If port 8000 stays busy, an orphaned reload worker holds it; end that Python process.

---

## 4. Model download at startup

The model file is not in Git or in the Docker image, so `backend/model_store.py` makes sure it exists when the app starts: it uses the local copy, or downloads it from `MODEL_URL` and verifies its SHA256.

Why this design: servers, CI and containers start from Git, which has no model; production teams keep weights as versioned artifacts in storage; and the same pattern scales to large models you could never commit.

| Situation at startup | What the app does |
| --- | --- |
| File exists, no checksum set | Uses it as is (your laptop) |
| File exists and matches `MODEL_SHA256` | Uses it, no download |
| File exists but differs, `MODEL_URL` set | Replaces it (a new model version) |
| File missing, `MODEL_URL` set | Downloads, verifies, saves, loads |
| Checksum wrong | Rejects the file, never saves it; `/health` shows `model_loaded: false` and the reason; `/predict` returns 503 |
| `MODEL_URL` set without `MODEL_SHA256` | Refused: the checksum is required |
| Plain `http://` to a remote host | Refused: only https (or http to localhost) |

SAS tokens in the URL are stripped from every error message. `/health` also reports `model_sha256` and `model_error`.

The two settings:

- `MODEL_URL`: where to download from (a SAS URL is a secret).
- `MODEL_SHA256`: the expected fingerprint. It is not secret. It proves the file is the exact one you meant, not corrupted or swapped.

Get the checksum of a model file:

```powershell
(Get-FileHash backend\models\model.onnx -Algorithm SHA256).Hash.ToLower()
```

This code only downloads. Uploading the model to Blob is a separate step (see section 8). Tests need no network:

```powershell
cd backend
.venv\Scripts\python.exe -m pytest -q   # 13 tests: download, bad checksum, bad URL, stale cache, token not leaked
```

---

## 5. Docker and Compose

A Dockerfile builds one image; `docker-compose.yml` runs several containers together and wires them up. Here there are two Dockerfiles (backend, frontend) and one compose file.

| File | Purpose |
| --- | --- |
| `backend/Dockerfile` | Slim Python 3.11 image, only runtime packages, runs as a non-root user, health check passes only when the model is loaded. The model is not baked in. |
| `frontend/Dockerfile` | Multi-stage: Node builds the React app, nginx serves it; the final image is small |
| `frontend/nginx.conf` | Serves React and proxies `/api/*` to the backend, so the browser uses one address and CORS is not an issue |
| `docker-compose.yml` | Builds both images, one network, a `models` volume, `MODEL_URL` / `MODEL_SHA256` as environment |
| `docker-compose.local-model.yml` | Test-only override: "downloads" your local model through a `file://` URL |
| `docker-compose.prod.yml` | For the VM: runs the images from GHCR instead of building |
| `.dockerignore`, `.gitattributes` | Keep junk out of images; force LF line endings for Linux |

Run the whole app in containers (needs Docker Desktop running):

```powershell
cd detection-app
$env:MODEL_SHA256 = (Get-FileHash backend\models\model.onnx -Algorithm SHA256).Hash.ToLower()
docker compose -f docker-compose.yml -f docker-compose.local-model.yml up --build
```

Open `http://localhost` and upload an image; check `http://localhost/api/health`. If port 80 is busy, change `"80:80"` to `"8080:80"` in `docker-compose.yml`.

Inspect and clean up:

```powershell
docker compose ps                              # status and health
docker compose logs -f backend                 # watch the model download and verify
docker compose exec backend bash               # shell inside the container (or: sh)
docker compose exec backend ls -la /app/models # the model lives here, in the volume
docker compose exec backend sha256sum /app/models/model.onnx
docker volume ls
docker images                                  # check image sizes
docker compose down                            # stop, keep the model volume
docker compose down -v                         # stop and delete the volume (forces a re-download)
```

To see a bad checksum rejected: `$env:MODEL_SHA256 = "0" * 64`, run `docker compose down -v`, start again; `/api/health` shows the reason and `docker compose ps` shows the backend unhealthy.

---

## 6. GitHub repository

Use one public monorepo (`detection-app`) holding frontend, backend and workflows. Public repos get unlimited Actions minutes and free GHCR images, and one repo means one place for secrets and pipelines.

1. On github.com, create a new **empty** repository named `detection-app` (Public). Leave README, .gitignore and license unticked.
2. Check `.gitignore` excludes `node_modules/`, `dist/`, `.venv/`, `.env*`, `*.pt` and `*.onnx`, so no model weights or secrets are committed.
3. Commit and push:

```powershell
cd detection-app
git config user.name "Your Name"
git config user.email "you@example.com"
git init -b main
git add .
git status          # check: no .venv, node_modules, dist, *.onnx, *.pt, .env
git commit -m "Initial commit"
git remote add origin https://github.com/<github-user>/detection-app.git
git push -u origin main
```

Notes:

- Use only the URL from GitHub's quick-start snippet. Its `echo >> README.md` and extra `git init` lines would overwrite your README.
- The commit email must be added and verified on your GitHub account for commits to link to your profile.
- `LF will be replaced by CRLF` warnings on Windows are harmless; `.gitattributes` forces LF for Linux containers.
- Never commit secrets. They go into GitHub Secrets (see section 10).

---

## 7. CI/CD pipeline with GitHub Actions

One workflow file, `.github/workflows/ci.yml`, is the whole pipeline. GitHub finds any `.yml` in `.github/workflows/` on its own, so nothing needs to be configured in a settings page.

| Job | What it does | Runs on |
| --- | --- | --- |
| Backend tests | Python 3.11, installs `requirements-dev.txt`, runs `pytest` (no model needed) | every push and PR |
| Frontend build | Node 20, `npm ci`, `npm run build` | every push and PR |
| Docker build and smoke test | Builds both images, starts the compose stack, checks `/api/health` through nginx and that the React page loads | every push and PR |
| Push images to GHCR | Pushes `detection-backend` and `detection-frontend`, tagged with the commit SHA and `latest` | `main` only |
| Deploy to Azure VM | Copies `docker-compose.prod.yml`, writes `.env` from secrets, pulls images, restarts, waits for `model_loaded: true` | `main` only, environment `production` |

How the deploy job works:

1. Writes the SSH key from the `VM_SSH_KEY` secret to a file and trusts the VM's host key for this run.
2. Copies `docker-compose.prod.yml` to `~/detection-app/docker-compose.yml` on the VM.
3. Writes a private `.env` there (`IMAGE_PREFIX`, `IMAGE_TAG` = commit SHA, `MODEL_URL`, `MODEL_SHA256`), sent over stdin so secrets never appear on a command line. Compose reads this file automatically; GitHub's secrets exist only on the runner, so they must be delivered to the VM.
4. Logs the VM into GHCR with the job's own token, then runs `docker compose pull` and `docker compose up -d`.
5. Polls `http://<VM_IP>/api/health` until it reports `model_loaded: true`; on failure it prints container logs.
6. Logs the VM out of GHCR.

Good to know:

- Pull requests run tests, build and smoke test only; they never deploy.
- Re-run everything by hand: Actions tab, CI/CD, **Run workflow**.
- The smoke test has no model (it is not in Git), so it proves the images build and nginx reaches FastAPI, not inference. Real inference is proven by the deploy job.
- A newer push cancels an older PR run but never a run that may be deploying.
- Tagging images with the commit SHA means any version can be redeployed, which is the basis of rollback.

---

## 8. Azure setup: Blob storage and the model

Store the model in a private Blob container and give the app a read-only SAS link. This costs a fraction of a cent for a 12 MB file.

**1. Sign in and create the storage** (PowerShell; the storage account name must be globally unique, lowercase):

```powershell
az login
$rg = "rg-demo"
$loc = "eastus"                # use a region your subscription allows
$sa = "detectionmodel" + (Get-Random -Maximum 99999)

az group create -n $rg -l $loc
az storage account create -n $sa -g $rg -l $loc --sku Standard_LRS --kind StorageV2 `
  --allow-blob-public-access false --min-tls-version TLS1_2
```

**2. Upload the model** (keep each version under its own path, never overwrite, so rollback is instant):

```powershell
cd detection-app
$key = az storage account keys list -g $rg -n $sa --query "[0].value" -o tsv
az storage container create --account-name $sa --account-key $key -n models --public-access off
az storage blob upload --account-name $sa --account-key $key -c models `
  -n v1/model.onnx -f backend\models\model.onnx --overwrite
```

**3. Create a read-only SAS URL.** In the portal: storage account, Containers, `models`, `v1/model.onnx`, **Generate SAS**; signing method Account key, permission **Read** only, HTTPS only, expiry after your demo date; copy the **Blob SAS URL** (shown once). Or by CLI:

```powershell
$expiry = (Get-Date).ToUniversalTime().AddDays(30).ToString("yyyy-MM-ddTHH:mmZ")
$env:MODEL_URL = az storage blob generate-sas --account-name $sa --account-key $key -c models `
  -n v1/model.onnx --permissions r --expiry $expiry --https-only --full-uri -o tsv
$env:MODEL_SHA256 = (Get-FileHash backend\models\model.onnx -Algorithm SHA256).Hash.ToLower()
```

Check the link works (prints only a status code; `200` is good, `403` is wrong permissions or expiry, `404` is a wrong path):

```powershell
curl.exe -s -o NUL -w "%{http_code}" "<blob SAS URL>"
```

**4. Test the real HTTPS download in Docker** before touching a VM:

```powershell
docker compose down -v
docker compose up --build        # plain compose file, MODEL_URL and MODEL_SHA256 set as above
curl.exe http://localhost/api/health
```

Why two values: the SAS URL gives permission to download (a secret; anyone with it can read that blob until it expires); the SHA256 proves the downloaded file is the right one. If the SAS expires, new downloads fail until you issue a new one; a model already cached on the VM keeps working.

---

## 9. Azure VM: create, SSH key, Docker

A 2 vCPU / 4 GiB Ubuntu VM is enough; 1 GiB sizes are too small and Arm64 sizes cannot run the x64 images. Everything below was done in the portal, except the SSH and Docker commands.

**1. Create the VM** (portal: Virtual machines, Create):

- Resource group `rg-demo`; name `vm-detection`; availability **No infrastructure redundancy required**.
- Image Ubuntu Server 24.04 (or 22.04) x64. Size: a B-series 2 vCPU / 4 GiB such as `Standard_B2s`, about $30/month. If the default size says `NotAvailableForSubscription`, click **See all sizes** and filter to B-series, or change region (we used West US 2).
- Authentication: either password or SSH public key (ours ended up with password login, which let us add our own key below); username `azureuser`; inbound ports **SSH (22)** and **HTTP (80)**.
- Disks: Standard SSD, tick **Delete with VM**. Networking: tick delete public IP and NIC with the VM.
- Management: enable **auto-shutdown** (for example 22:00) as a safety net.
- If you chose "Generate new key pair", download the `.pem` when prompted; Azure never offers it again.

**2. Create your own deploy key** (we did not get the `.pem`, so we made one; this is also the safest route). On your PC:

```powershell
ssh-keygen -t ed25519 -f "$HOME\.ssh\detection_deploy" -N '""' -C "detection-deploy"
scp "$HOME\.ssh\detection_deploy.pub" azureuser@<VM_IP>:/tmp/deploy.pub
```

The first `scp` asks for the VM password. Then on the VM, as `azureuser` (copying the file instead of pasting avoids hidden Windows line endings):

```bash
cat /tmp/deploy.pub | tr -d '\r' > /home/azureuser/.ssh/authorized_keys
chown azureuser:azureuser /home/azureuser/.ssh/authorized_keys
chmod 700 /home/azureuser/.ssh
chmod 600 /home/azureuser/.ssh/authorized_keys
```

Test key-only login from your PC (it must print `key works` without asking for a password):

```powershell
ssh -i "$HOME\.ssh\detection_deploy" -o IdentitiesOnly=yes -o PasswordAuthentication=no azureuser@<VM_IP> "echo key works"
```

The private file `detection_deploy` (no `.pub`) becomes the `VM_SSH_KEY` secret; never share or commit it.

**3. Install Docker on the VM:**

```powershell
ssh -i "$HOME\.ssh\detection_deploy" azureuser@<VM_IP> "curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker azureuser"
ssh -i "$HOME\.ssh\detection_deploy" azureuser@<VM_IP> "docker --version && docker compose version && docker run --rm hello-world"
```

The `get.docker.com` script is fine for a demo; production setups pin versions and install from the apt repository. Without SSH, the portal route is VM, Operations, Run command, RunShellScript, with the same two install commands (no `sudo` needed there).

**4. Check the network:** the VM's Networking tab must show inbound rules for ports 22 and 80. Password login stays enabled until you turn it off; do that only after the key test passes.

---

## 10. GitHub secrets, first deploy, verification

Five secrets in a GitHub environment called `production` are all the pipeline needs. No Azure client ID or password is used because deployment goes over SSH.

Create the environment: repo **Settings, Environments, New environment**, name `production` (no approval gate in our setup). Then **Add environment secret** for each:

| Secret | Value | How to get it |
| --- | --- | --- |
| `VM_HOST` | The VM's public IP | VM Overview page |
| `VM_USER` | `azureuser` | The username you set |
| `VM_SSH_KEY` | Entire private key file, with BEGIN and END lines | `Get-Content "$HOME\.ssh\detection_deploy" -Raw \| Set-Clipboard`, then paste |
| `MODEL_URL` | Blob SAS URL of `v1/model.onnx` | Portal Generate SAS (read only, expiry after the demo) |
| `MODEL_SHA256` | Checksum of the model file | `(Get-FileHash backend\models\model.onnx -Algorithm SHA256).Hash.ToLower()` |

Paste values only into GitHub, never into chat or code. `GITHUB_TOKEN` is provided automatically and logs the VM into GHCR for the pull.

First deploy and verification:

1. Push to `main` (or Actions, CI/CD, Run workflow).
2. Open the Actions tab and watch the run: Backend tests and Frontend build in parallel, then Docker build and smoke test, Push images to GHCR, Deploy to Azure VM (our first run took about 2.5 minutes).
3. Open `http://<VM_IP>` and upload an image from `test-images`.
4. Open `http://<VM_IP>/api/health`: expect `"model_loaded":true` and the model's SHA256.
5. On the VM you can see the deployed files in `/home/azureuser/detection-app` (`docker-compose.yml`, `.env` with mode 600).

Useful checks on the VM:

```powershell
ssh -i "$HOME\.ssh\detection_deploy" azureuser@<VM_IP> "cd ~/detection-app && docker compose ps && docker compose logs --tail 50"
```

---

## 11. Troubleshooting

These are the problems we actually hit while building this, with the fix for each.

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Failed to fetch` in the UI | Backend is not running on port 8000 | Start uvicorn; open the page at `http://localhost:5173` |
| Port 8000 still busy after stopping | Orphaned `--reload` worker process | End that Python process |
| `python` or `pip` not found | Not installed or PATH not refreshed | `winget install ...`, open a new terminal |
| `Activate.ps1` or `uvicorn.exe` fails after renaming the folder | Launchers hold the old absolute path | Use `.venv\Scripts\python.exe -m uvicorn ...`, or recreate the venv |
| `pip install` of PyTorch is very slow | Large download on a slow link | Wait; it is needed once, only for `export_model.py` |
| Download failed leaving a `.part` file (Windows) | File handle left open on a failed download | Fixed in `model_store.py`; covered by a test |
| `model_loaded: false` with a checksum error | `MODEL_SHA256` does not match the file | Recompute the hash of the exact uploaded file |
| `model_loaded: false`, download error or 403 | SAS URL expired or has the wrong permissions | Generate a new read-only SAS; update the `MODEL_URL` secret and redeploy |
| `NotAvailableForSubscription` when creating the VM | Size or region restricted for this subscription | See all sizes, pick a 2 vCPU / 4 GiB B-series, or change region; avoid 1 GiB and Arm64 |
| No `.pem` was downloaded | Dialog missed, or password authentication was chosen | Create your own key with `ssh-keygen` and install the public key |
| `Permission denied (publickey,password)` | `authorized_keys` empty, wrong user, or Windows line endings | Copy the `.pub` with `scp`, strip `\r`, fix owner and modes |
| Commands ran as root and changed `/root/.ssh` | `~` means `/root` when you are root | Use full paths `/home/azureuser/...`, or `exit` root first |
| `key works` printed after a password prompt | Key was rejected, password accepted | Test with `-o PasswordAuthentication=no` |
| `docker: command not found` on the VM | Docker not installed yet | Run the install command |
| Deploy health check times out | Port 80 closed, or model not loaded | Open port 80 in Networking; read the failure logs the job prints |
| GHCR pull denied on the VM | Package private and login failed | Make the packages public (profile, Packages, settings) |
| Port 80 busy on your PC | Another program uses it | Map `"8080:80"` in `docker-compose.yml` |

---

## 12. Cleanup, cost control and next steps

When the session ends, delete the resource group. That removes the VM, disk, IP and storage account in one step and stops all billing.

Cleanup in the portal: Resource groups, `rg-demo`, **Delete resource group**, type its name. Or by CLI:

```powershell
az group delete -n rg-demo --yes --no-wait
```

The next morning, check Cost Management, Cost analysis, to confirm nothing is left. Keep a local copy of `model.onnx` (deleting the group also deletes the blob).

Cost reminders:

- A B2s VM costs about $0.04 per hour; a short demo costs cents.
- Stopped but not deallocated: still billed for compute. Deallocated: only disk and IP. Deleted group: nothing.
- Auto-shutdown is a safety net, not a replacement for deleting.

Optional next steps:

- A manual workflow to swap the model (new `MODEL_URL` and `MODEL_SHA256`) and to roll back to an older image tag, with no image rebuild.
- Turn off SSH password login once key login works.
- HTTPS, which needs a domain name.
- Commit the sample test images only after checking their licenses (COCO images carry per-image Creative Commons licenses).
- For large models: keep the model in storage and download it at startup (this pattern), use a cache volume, and for very large or GPU models consider a separate model service or a managed endpoint.
