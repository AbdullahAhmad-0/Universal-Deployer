# 🚀 Universal Deployer

A modern, declarative, and color-rich deployment CLI tool for web applications, Docker containers, and static sites. Deploy seamlessly from your local machine to any Linux VPS or hosting server using **SSH/SFTP** or **FTP**.

---

## ✨ Features

- **YAML + Dockerfile-Style Syntax**: Configure complex builds and deployments using intuitive directives like `RUN`, `COPY`, `CMD`, `WORKDIR`, and `ENV`.
- **Interactive File Discovery**: If `deploy.yml` is not found in the current folder, the script prompts you to enter your project directory or file path automatically.
- **Dual Protocol Support**:
  - **SSH / SFTP**: Full remote terminal execution (`paramiko`), automated directory sync, and Docker container orchestration.
  - **FTP**: Built-in FTP transfer (`ftplib`) for static/shared hosting environments (with graceful warnings for unsupported remote commands).
- **Flexible Docker Workflows**:
  - **Local Build & Tar Transfer (Default)**: Builds the Docker image locally, exports it to a `.tar` archive, transfers it via SFTP, and loads it into the remote Docker daemon. This saves RAM and CPU on low-spec VPS servers!
  - **Remote Build**: Syncs files and triggers `docker compose build` directly on the VPS.
- **Traditional (No Docker) Deployments**: Perfect for static frontends (React, Vue, Next.js static exports, Vite) or traditional Node/Python/PHP apps with local builds and Nginx reloading.
- **Dynamic Variable Substitution**: Seamlessly interpolate `${VPS_IP}`, `${SSH_KEY_PATH}`, or custom environment variables from `.env` or `.env.deploy` files.
- **Rich Terminal UI**: Full ANSI color formatting with `colorama`, interactive numbered selection menus, step badges (`[Docker]`, `[SSH]`, `[FTP]`), and upload progress bars.

---

## 📦 Installation & Requirements

Ensure you have Python 3.9+ installed. Install the required dependencies:

```bash
pip install -r requirements.txt
```

*(Note: If you only use FTP deployments, `paramiko` is optional!)*

---

## ⚡ Quick Start

### 1. Initialize Configuration
Generate a starter `deploy.yml` file in your project directory:

```bash
python deploy.py --init
```

Or view a commented example in your terminal:

```bash
python deploy.py --example
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
python deploy.py

# Or deploy a specific service directly
python deploy.py frontend

# Or deploy all services in order
python deploy.py all
```

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
      service_name: backend            # Name of service inside docker-compose.yml
      build_mode: local                # "local" (build tarball & upload) or "remote"
      image: my-backend:latest
      context: ./backend
      dockerfile: ./backend/Dockerfile # (Optional)

    # Remote steps executed on VPS BEFORE starting Docker:
    before_deploy:
      - RUN mkdir -p ${remote_dir}/backend/data
      - COPY ./backend/.env.production -> ${remote_dir}/backend/.env

    # Remote steps executed on VPS AFTER starting Docker:
    run_in_vps:
      - RUN docker compose up -d backend
      - RUN docker compose ps
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

## 🔒 SSH vs. 📡 FTP Differences

| Feature | SSH / SFTP | FTP (`ftplib`) |
|---------|:----------:|:--------------:|
| File & Directory Sync | ✅ Yes | ✅ Yes |
| Progress Indicator | ✅ Yes | ✅ Yes |
| Remote Shell Execution (`RUN`) | ✅ Yes | ❌ Not supported by FTP |
| Docker Container Management | ✅ Yes | ❌ Not supported by FTP |
| Authentication | Key file, Passphrase, or Password | Username & Password |

> [!NOTE]
> When `type: ftp` is selected, any remote command steps (e.g. `run_in_vps`) are safely skipped with a helpful warning notice instead of breaking your deployment.

---

## 🖥️ Command-Line Interface (CLI)

```
Usage:
  python deploy.py [OPTIONS] [SERVICE_NAME]

Options:
  -h, --help               Show full colorful help screen and exit.
  -e, --example            Display a syntax-highlighted example deploy.yml.
  --init                   Generate a starter deploy.yml in the current directory.
  -f, --file PATH          Specify path to deploy configuration file.
  -p, --project DIR        Specify project directory containing deploy configuration.
  -s, --service NAME       Name of service to deploy (or 'all').
  -l, --list               List all services available in the configuration file.
  --dry-run                Validate configuration and simulate steps without connecting.
```

### CLI Examples

```bash
# Preview build and deployment steps without making server changes:
python deploy.py backend --dry-run

# List configured services in a custom deploy file:
python deploy.py -f ./custom-deploy.yml --list

# Deploy a specific service from an external project directory:
python deploy.py -p D:/Projects/my-app frontend
```

---

## 📄 License

MIT License. Feel free to customize and extend for your deployment pipelines!

