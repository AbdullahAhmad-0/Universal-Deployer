# 🚀 uhdeploy - Universal Deployer CLI

A modern, declarative, and color-rich deployment CLI tool for web applications, Docker containers, and static sites. Deploy seamlessly from your local machine to any Linux VPS or hosting server using **SSH/SFTP** or **FTP**.

---

## 📦 Installation

Install `uhdeploy` directly via pip:

```bash
pip install uhdeploy
```

Or install from source for development:

```bash
git clone https://github.com/AbdullahAhmad-0/Universal-Deployer.git
cd Universal-Deployer
pip install -e .
```

---

## ✨ Features

- **Global CLI Command**: Run `uhdeploy` anywhere in your terminal.
- **YAML + Dockerfile-Style Syntax**: Configure complex builds and deployments using intuitive directives like `RUN`, `COPY`, `CMD`, `WORKDIR`, and `ENV`.
- **Interactive File Discovery**: If `deploy.yml` is not found in the current folder, `uhdeploy` prompts you to enter your project directory or file path automatically.
- **Dual Protocol Support**:
  - **SSH / SFTP**: Full remote terminal execution (`paramiko`), automated directory sync, and Docker container orchestration.
  - **FTP**: Built-in FTP transfer (`ftplib`) for static/shared hosting environments (with graceful warnings for unsupported remote commands).
- **Blazing Fast Multi-Threaded Uploads**: High-concurrency parallel SFTP/FTP transfers (default 8 threads, configurable up to 32) using persistent channel multiplexing.
- **Auto-Reconnect & Retry**: Automatically detects dropped SSH/FTP connections, re-establishes authentication, and retries file transfers without failing the deployment.
- **Ultra-Fast Archive Mode (`--archive`)**: Package 1,000+ files into a compressed in-memory archive, upload in 1 second, and extract instantly on the remote VPS.
- **Skip Existing Files Option (`overwrite: false` / `--no-overwrite`)**: By default, `uhdeploy` automatically overwrites matching files on the destination server. If you want to preserve existing server files and skip uploading them, simply set `overwrite: false` or pass `--no-overwrite`.
- **Flexible Docker Workflows**:
  - **Local Build & Tar Transfer (Default)**: Builds the Docker image locally, exports it to a `.tar` archive, transfers it via SFTP, and loads it into the remote Docker daemon. This saves RAM and CPU on low-spec VPS servers!
  - **Remote Build**: Syncs files and triggers `docker compose build` directly on the VPS.
  - **Auto Environment Sync**: Automatically detects and syncs environment files (e.g. `.env.production`) referenced in your `docker-compose.yml`.
- **Traditional (No Docker) Deployments**: Perfect for static frontends (React, Vue, Next.js static exports, Vite) or traditional Node/Python/PHP apps with local builds and Nginx reloading.
- **Dynamic Variable Substitution**: Seamlessly interpolate `${VPS_IP}`, `${SSH_KEY_PATH}`, or custom environment variables from `.env` or `.env.deploy` files.
- **Rich Terminal UI**: Full ANSI color formatting with `colorama`, interactive numbered selection menus, step badges (`[Docker]`, `[SSH]`, `[FTP]`), and upload progress bars.

---

## ⚡ Quick Start

### 1. Initialize Configuration
Generate a starter `deploy.yml` file in your project directory:

```bash
uhdeploy --init
```

Or view a commented example in your terminal:

```bash
uhdeploy --example
```

### 2. Configure Environment Variables (`.env`)
Create a `.env` file in your project root with your server credentials:

```dotenv
VPS_IP=123.45.67.89
VPS_USER=root
SSH_KEY_PATH=~/.ssh/id_rsa
SSH_PORT=22
# Optional:
SSH_PASSPHRASE=
VPS_PASSWORD=
```

### 3. Run Deployer
Launch the deployer:

```bash
# Interactive service selection menu
uhdeploy

# Or deploy a specific service directly
uhdeploy frontend

# Or deploy all services in order
uhdeploy all
```

*(You can also run it via `python -m uhdeploy` or `python deploy.py`)*

---

## 🛠️ Configuration Guide (`deploy.yml`)

The configuration file defines global server credentials and individual service deployment pipelines.

```yaml
# =============================================================================
# 🌐 GLOBAL SERVER SETTINGS (Inherited by all services)
# =============================================================================
server:
  type: ssh                    # "ssh" (SFTP + Shell) or "ftp" (File transfer only)
  host: ${VPS_IP}              # VPS Hostname or IP (from .env)
  user: ${VPS_USER:-root}      # SSH/FTP Username (defaults to root)
  port: 22                     # Port: 22 for SSH, 21 for FTP
  key_path: ${SSH_KEY_PATH}    # Path to private key file
  passphrase: ${SSH_PASSPHRASE}# (Optional) Private key passphrase
  password: ${VPS_PASSWORD}    # (Optional) SSH or FTP password
  remote_dir: /opt/my-app      # Remote base directory on VPS
  threads: 8                   # (Optional) Parallel upload threads (default: 8)
  retries: 5                   # (Optional) Auto-reconnect & retry attempts (default: 5)
  # archive: true              # (Optional) Ultra-fast 1-shot archive sync (SSH only)
  # overwrite: false           # (Optional) Set false to skip files that already exist on server (default: true)

# Optional custom env file to load (default: .env or .env.deploy)
env_file: .env

# =============================================================================
# 📦 SERVICES DEFINITION
# =============================================================================
services:

  # ---------------------------------------------------------------------------
  # 1. Frontend Service (WITHOUT DOCKER)
  # ---------------------------------------------------------------------------
  frontend:
    description: "Build Next.js / React frontend and sync static files"
    docker: false              # Disable docker for this service
    work_dir: ./frontend       # Working directory relative to project root

    # Local build steps (Dockerfile-style string commands):
    build:
      - RUN npm install
      - RUN npm run build
      - COPY package.json dist/package.json

    # Upload files or directories to the VPS:
    upload:
      - dist/ -> ${remote_dir}/frontend/dist
      - public/ -> ${remote_dir}/frontend/public

    # (Optional) Wipe remote destination directory before uploading:
    # clean_remote: true

    # Commands executed on VPS after uploading (SSH only):
    run_in_vps:
      - RUN systemctl reload nginx
      - RUN echo "Frontend updated and Nginx reloaded!"

  # ---------------------------------------------------------------------------
  # 2. Backend Service (WITH DOCKER)
  # ---------------------------------------------------------------------------
  backend:
    description: "FastAPI / Node API running in Docker Compose"
    work_dir: ./backend

    docker:
      enabled: true
      compose_file: docker-compose.yml # Compose file (defaults to docker-compose.yml)
      # (Optional: .env.production referenced in compose is auto-synced!)
      service_name: backend            # Name of service inside docker-compose.yml
      build_mode: local                # "local" (build tarball & upload) or "remote"
      image: my-backend:latest
      context: ./backend
      dockerfile: ./backend/Dockerfile # (Optional)

    # Remote steps executed on VPS BEFORE starting Docker:
    before_deploy:
      - RUN mkdir -p ${remote_dir}/backend/data

    # Remote steps executed on VPS AFTER starting Docker:
    # (Note: 'docker compose up -d <service>' is already executed automatically!)
    run_in_vps:
      - RUN docker compose ps
      - RUN docker compose logs --tail=25 backend

  # ---------------------------------------------------------------------------
  # 3. API / Worker (Direct Working Directory Upload with Ignore Rules)
  # ---------------------------------------------------------------------------
  api:
    description: "Sync current working directory directly to VPS with ignore rules"
    docker: false
    work_dir: ./api

    # Upload entire working directory (.) to remote VPS destination:
    upload:
      - . -> ${remote_dir}/api

    # Files and folders to ignore when uploading:
    # (You can also put these into a .deployignore file!)
    ignore:
      - node_modules
      - .venv
      - venv
      - __pycache__
      - .git
      - .env.local
      - "*.log"
      - "*.pyc"

    # (Optional) Wipe destination directory before uploading:
    # clean_remote: true

    run_in_vps:
      - RUN pm2 restart api || pm2 start index.js --name api
```

---

## 🧩 Step Directives Reference

Within `build`, `before_deploy`, and `run_in_vps`, you can write steps as clean strings or structured objects:

| Directive | Example | Description |
|-----------|---------|-------------|
| `RUN <cmd>` | `- RUN npm run build` | Runs a shell command (locally in `build`, or on the VPS in `before_deploy` / `run_in_vps`). |
| `CMD <cmd>` | `- CMD python manage.py migrate` | Alias for `RUN`. |
| `COPY <src> <dst>` | `- COPY ./dist -> ${remote_dir}/dist` | Copies local files/folders locally or uploads them to the remote server. |
| `WORKDIR <dir>` | `- WORKDIR ./subfolder` | Changes current working directory for subsequent steps. |
| `ENV <k>=<v>` | `- ENV NODE_ENV=production` | Sets an environment variable for subsequent steps. |

---

## 📁 Directory Uploads, Ignore Rules & Clean Remote

### 1. Uploading Current Working Directory (`.`)
If you want to upload the entire codebase of your working directory (e.g., Python, Node.js, PHP, or Go apps) rather than just a `dist/` subfolder, specify `.`:

```yaml
upload:
  - . -> ${remote_dir}/api
```

### 2. Ignoring Files and Folders (`ignore:`)
When uploading directories, you can exclude heavy, generated, or sensitive files using the `ignore:` (or `exclude:`) list in your `deploy.yml`:

```yaml
ignore:
  - node_modules
  - .venv
  - venv
  - __pycache__
  - .git
  - .env.local
  - "*.log"
  - "*.pyc"
```

> [!TIP]
> **Fast Folder Pruning**: Ignored directories like `node_modules` or `.venv` are never traversed, ensuring fast uploads without scanning tens of thousands of unnecessary files.

### 3. Using `.deployignore`
You can also place a **`.deployignore`** file in your service directory or project root using standard `.gitignore` syntax. `uhdeploy` will detect and apply these rules automatically.

### 4. Overwrite Behavior vs. Skip Existing (`overwrite: false` / `--no-overwrite`) vs. `clean_remote`
- **Default (Automatic Overwrite)**: You do not need to configure anything! `uhdeploy` automatically overwrites matching files on the destination server. Non-conflicting files on the server (like database files, user uploads, runtime logs) **remain untouched and safe**.
- **Skip Existing Files (`overwrite: false` or `--no-overwrite`)**: When you want to preserve existing files on the remote server and ONLY upload new or missing files, set:
  ```yaml
  overwrite: false   # Skip files that already exist on the server (default: true)
  ```
  Or pass `--no-overwrite` via the CLI:
  ```bash
  uhdeploy backend --no-overwrite
  ```
- **Wiping Destination Folder (`clean_remote: true`)**: If you want to completely empty/wipe the target directory on the VPS before uploading fresh files, set:
  ```yaml
  clean_remote: true
  ```

---

## ⚡ High-Performance Uploads (Threads, Retries & Archive Sync)

`uhdeploy` includes cutting-edge features to accelerate large transfers and survive unstable network connections:

1. **Multi-Threaded Uploads (`threads: 8` / `-t N`)**:
   Instead of uploading sequentially, `uhdeploy` opens dedicated SFTP/FTP worker threads to upload multiple files in parallel. You can customize the thread count per-service or via the CLI flag `-t 16`.
2. **Auto-Reconnect & Retry (`retries: 5` / `--retries N`)**:
   If a network glitch or VPS timeout disconnects the SFTP/FTP channel, `uhdeploy` automatically reconnects, re-authenticates, and resumes transferring without failing your deployment.
3. **Ultra-Fast Archive Mode (`archive: true` / `--archive`)**:
   For directories containing hundreds or thousands of files, file-by-file SFTP handshakes can be slow. With Archive Mode enabled, `uhdeploy` packages all non-ignored files into a compressed `.tar.gz` in memory, uploads it in a single shot, and extracts it directly on the remote VPS in seconds!
   ```yaml
   archive: true   # Enable fast archive packaging and sync (SSH only)
   ```

---

## 🔒 SSH vs. 📡 FTP Differences

| Feature | SSH / SFTP | FTP (`ftplib`) |
|---------|:----------:|:--------------:|
| File & Directory Sync | ✅ Yes | ✅ Yes |
| Progress Indicator | ✅ Yes | ✅ Yes |
| Remote Shell Execution (`RUN`) | ✅ Yes | ❌ Not supported by FTP |
| Docker Container Management | ✅ Yes | ❌ Not supported by FTP |
| Multi-Threaded Transfers | ✅ Yes (up to 32 threads) | ✅ Yes (up to 16 threads) |
| Auto-Reconnect & Retry | ✅ Yes | ✅ Yes |
| Archive Mode Fast Extraction | ✅ Yes (Remote `tar -xzf`) | ❌ Not supported by FTP |
| Authentication | Key file, Passphrase, or Password | Username & Password |

> [!NOTE]
> When `type: ftp` is selected, any remote command steps (e.g. `run_in_vps`) are safely skipped with a helpful warning notice instead of breaking your deployment.

---

## 🖥️ Command-Line Interface (CLI)

```
Usage:
  uhdeploy [OPTIONS] [SERVICE_NAME]
  (or python -m uhdeploy [OPTIONS] [SERVICE_NAME])

Options:
  -h, --help               Show full colorful help screen and exit.
  -e, --example            Display a syntax-highlighted example deploy.yml.
  --init                   Generate a starter deploy.yml in the current directory.
  -f, --file PATH          Specify path to deploy configuration file.
  -p, --project DIR        Specify project directory containing deploy configuration.
  -s, --service NAME       Name of service to deploy (or 'all').
  -l, --list               List all services available in the configuration file.
  -t, --threads N          Number of concurrent upload threads (default: 8).
  --retries N              Max retry & reconnect attempts on network drops (default: 5).
  --archive                Package files into compressed archive for fast sync (SSH only).
  --overwrite              Force overwrite existing files on destination server (default behavior).
  --no-overwrite           Do not overwrite files that already exist on server (skip existing).
  --dry-run                Validate configuration and simulate steps without connecting.
```

### CLI Examples

```bash
# Preview build and deployment steps without making server changes:
uhdeploy backend --dry-run

# Deploy with ultra-fast archive sync (single-shot tarball):
uhdeploy frontend --archive

# Deploy with 16 parallel upload threads:
uhdeploy api -t 16

# Deploy without overwriting existing files on the server:
uhdeploy backend --no-overwrite

# List configured services in a custom deploy file:
uhdeploy -f ./custom-deploy.yml --list

# Deploy a specific service from an external project directory:
uhdeploy -p D:/Projects/my-app frontend
```

---

## 🚢 Publishing to PyPI

To build and publish `uhdeploy` to PyPI:

1. **Install build tools**:
   ```bash
   pip install --upgrade build twine
   ```

2. **Build distribution packages (tar.gz and .whl)**:
   ```bash
   python -m build
   ```

3. **Check distribution packages**:
   ```bash
   twine check dist/*
   ```

4. **Upload to PyPI**:
   ```bash
   twine upload dist/*
   ```

Once published, anyone can install your package with:
```bash
pip install uhdeploy
```

---

## 📄 License

MIT License. Created by Abdullah Ahmad. Feel free to customize and extend for your deployment pipelines!
