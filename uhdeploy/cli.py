#!/usr/bin/env python3
"""
=============================================================================
🚀 uhdeploy - Universal Deployer CLI
=============================================================================
A modern, declarative deployment tool for web applications, Docker containers,
and static websites to VPS instances. Supports Dockerfile-style step pipelines,
SSH/SFTP and FTP protocols, interactive configuration discovery, and full-color
terminal feedback.
=============================================================================
"""

import os
import sys
import re
import shutil
import subprocess
import argparse
import ftplib
import fnmatch
import threading
import time
import tarfile
import tempfile
import concurrent.futures
from pathlib import Path

# Ensure UTF-8 output encoding for consoles (especially Windows)
if sys.platform == "win32":
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Colorama for cross-platform ANSI colors
try:
    import colorama
    from colorama import Fore, Back, Style
    colorama.init(autoreset=True)
except ImportError:
    # Graceful fallback if colorama is missing
    class DummyColor:
        def __getattr__(self, name):
            return ""
    Fore = Back = Style = DummyColor()

# PyYAML
try:
    import yaml
except ImportError:
    print(f"{Fore.RED}❌ Error: The 'pyyaml' library is required to run uhdeploy.{Style.RESET_ALL}")
    print("Please install it using: pip install pyyaml")
    sys.exit(1)

# Paramiko for SSH / SFTP
try:
    import paramiko
except ImportError:
    paramiko = None


# =============================================================================
# 🎨 COLORFUL LOGGING & UI HELPERS
# =============================================================================

def banner():
    lines = [
        f"{Fore.CYAN}╔═══════════════════════════════════════════════════════════════════════════╗",
        f"║ {Fore.CYAN}{Style.BRIGHT}🚀  U H D E P L O Y   -   U N I V E R S A L   D E P L O Y E R             {Style.NORMAL}{Fore.CYAN}║",
        f"║ {Fore.YELLOW}Local-to-VPS Automated Deployment (SSH / SFTP / FTP / Docker)             {Fore.CYAN}║",
        f"╚═══════════════════════════════════════════════════════════════════════════╝{Style.RESET_ALL}"
    ]
    print("\n" + "\n".join(lines) + "\n")

def log_info(msg):
    print(f"{Fore.CYAN}ℹ️  {msg}{Style.RESET_ALL}")

def log_step(service, step_type, msg):
    print(f"\n{Fore.MAGENTA}┌─ [{Fore.WHITE}{Style.BRIGHT}{service}{Style.NORMAL}{Fore.MAGENTA}] [{Fore.YELLOW}{step_type}{Fore.MAGENTA}]{Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}└─▶ {Fore.WHITE}{msg}{Style.RESET_ALL}")

def log_success(msg):
    print(f"{Fore.GREEN}{Style.BRIGHT}✅ {msg}{Style.RESET_ALL}")

def log_warning(msg):
    print(f"{Fore.YELLOW}⚠️  {msg}{Style.RESET_ALL}")

def log_error(msg):
    print(f"{Fore.RED}{Style.BRIGHT}❌ {msg}{Style.RESET_ALL}", file=sys.stderr)

def log_cmd(cmd, kind="LOCAL"):
    color = Fore.CYAN if kind == "LOCAL" else Fore.YELLOW
    print(f"{color}[{kind}] > {Fore.WHITE}{cmd}{Style.RESET_ALL}")

def print_separator(char="─", length=75, color=Fore.CYAN):
    print(f"{color}{char * length}{Style.RESET_ALL}")


# =============================================================================
# 🔍 CONFIGURATION FILE DISCOVERY
# =============================================================================

CONFIG_CANDIDATES = [
    "deploy.yml",
    "deploy.yaml",
    "Deployfile.yml",
    "Deployfile.yaml",
    "Deployfile",
    ".deploy.yml",
    ".deploy.yaml",
    ".env.deploy"
]

def search_candidate_in_dir(directory):
    if not os.path.isdir(directory):
        return None
    for name in CONFIG_CANDIDATES:
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate):
            return candidate
    return None

def find_config_interactive(cli_file=None, cli_project=None):
    """
    Finds the deployment configuration file following the required flow:
    1. Check CLI specified --file or --project
    2. Check current folder
    3. If not found, show message and ask for project path
    4. If not found in project path, ask for direct file path
    """
    # 1. Direct CLI file provided
    if cli_file:
        resolved = os.path.abspath(cli_file)
        if os.path.isfile(resolved):
            return resolved, os.path.dirname(resolved)
        log_error(f"Config file specified with --file was not found: '{cli_file}'")
        sys.exit(1)

    # 2. CLI project directory provided
    if cli_project:
        resolved_proj = os.path.abspath(cli_project)
        candidate = search_candidate_in_dir(resolved_proj)
        if candidate:
            return candidate, resolved_proj
        log_error(f"No deploy config file found in project directory: '{cli_project}'")
        sys.exit(1)

    # 3. Check current folder
    cwd = os.getcwd()
    candidate = search_candidate_in_dir(cwd)
    if candidate:
        return candidate, cwd

    # 4. Not found in current directory - Interactive prompt
    log_warning(f"No deploy configuration file ({', '.join(CONFIG_CANDIDATES[:2])}) found in current directory:")
    print(f"    {Fore.LIGHTBLACK_EX}{cwd}{Style.RESET_ALL}")

    while True:
        try:
            prompt = f"\n{Fore.CYAN}👉 Enter project path {Fore.LIGHTBLACK_EX}(or press Enter to specify file directly): {Style.RESET_ALL}"
            proj_input = input(prompt).strip().strip('"').strip("'")
        except (KeyboardInterrupt, EOFError):
            print(f"\n{Fore.YELLOW}Deployment cancelled by user.{Style.RESET_ALL}")
            sys.exit(0)

        if not proj_input:
            break

        proj_dir = os.path.abspath(os.path.expanduser(proj_input))
        if not os.path.isdir(proj_dir):
            log_error(f"Project folder not found: '{proj_input}'. Please enter a valid directory.")
            continue

        candidate = search_candidate_in_dir(proj_dir)
        if candidate:
            log_success(f"Found deployment configuration in '{proj_dir}': {os.path.basename(candidate)}")
            return candidate, proj_dir
        else:
            log_warning(f"No deploy configuration file found inside '{proj_input}'.")
            break

    # 5. Ask for direct file path
    while True:
        try:
            prompt = f"\n{Fore.CYAN}👉 Enter deploy configuration file path {Fore.LIGHTBLACK_EX}(e.g. ./deploy.yml): {Style.RESET_ALL}"
            file_input = input(prompt).strip().strip('"').strip("'")
        except (KeyboardInterrupt, EOFError):
            print(f"\n{Fore.YELLOW}Deployment cancelled by user.{Style.RESET_ALL}")
            sys.exit(0)

        if not file_input:
            log_error("No file path entered. Cannot proceed with deployment.")
            sys.exit(1)

        file_path = os.path.abspath(os.path.expanduser(file_input))
        if os.path.isfile(file_path):
            log_success(f"Using configuration file: {file_path}")
            return file_path, os.path.dirname(file_path)
        else:
            log_error(f"File not found: '{file_input}'. Please verify the path.")


# =============================================================================
# 📄 ENVIRONMENT VARIABLES & CONFIG PARSING
# =============================================================================

def load_env_file(filepath):
    """Parses standard KEY=VALUE environment files into a dictionary."""
    if not os.path.isfile(filepath):
        return {}
    env_vars = {}
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                val = val.strip().strip('"').strip("'")
                env_vars[key.strip()] = val
    return env_vars

# Protected runtime variables that are resolved at deployment runtime or config parsing
PROTECTED_VARS = {"remote_dir", "dest", "remote_base", "vps_dir"}

def substitute_env_vars(raw_text, env_dict, protect_keys=True):
    """
    Substitutes ${VAR} and ${VAR:-default} and $VAR with environment values.
    Preserves protected keys like ${remote_dir} if not explicitly defined in env_dict.
    """
    def replace_bracket(match):
        expr = match.group(1)
        if ":-" in expr:
            var_name, default_val = expr.split(":-", 1)
        else:
            var_name, default_val = expr, None

        if var_name in env_dict:
            return str(env_dict[var_name])
        if var_name in os.environ:
            return os.environ[var_name]
        if default_val is not None:
            return default_val
        if protect_keys and var_name in PROTECTED_VARS:
            return match.group(0)  # Keep ${remote_dir} intact!
        return ""

    def replace_simple(match):
        var_name = match.group(1)
        if var_name in env_dict:
            return str(env_dict[var_name])
        if var_name in os.environ:
            return os.environ[var_name]
        if protect_keys and var_name in PROTECTED_VARS:
            return match.group(0)
        return f"${var_name}"

    # Replace ${VAR:-default} and ${VAR}
    result = re.sub(r"\$\{([A-Za-z0-9_]+(?::-.*?|)?)\}", replace_bracket, raw_text)
    # Replace $VAR (only if word boundary)
    result = re.sub(r"\$([A-Za-z0-9_]+)", replace_simple, result)
    return result

def parse_deploy_config(config_path, project_root):
    """
    Reads deploy.yml, substitutes env vars, and normalizes service definitions.
    """
    # Load .env files from project_root if available
    env_dict = {}
    default_env = os.path.join(project_root, ".env")
    if os.path.isfile(default_env):
        env_dict.update(load_env_file(default_env))

    deploy_env = os.path.join(project_root, ".env.deploy")
    if os.path.isfile(deploy_env):
        env_dict.update(load_env_file(deploy_env))

    with open(config_path, "r", encoding="utf-8", errors="replace") as f:
        raw_content = f.read()

    # If the file specifies custom env_file:
    custom_env_match = re.search(r"^\s*env_file:\s*(.+)$", raw_content, re.MULTILINE)
    if custom_env_match:
        custom_env_name = custom_env_match.group(1).strip().strip('"').strip("'")
        custom_env_path = os.path.join(project_root, custom_env_name)
        if os.path.isfile(custom_env_path):
            env_dict.update(load_env_file(custom_env_path))

    # Add runtime helper variables
    env_dict["PROJECT_DIR"] = project_root

    # Pre-extract server.remote_dir from configuration so ${remote_dir} is immediately available
    remote_dir_match = re.search(r"^\s*remote_dir:\s*['\"]?([^'\"#\r\n]+)['\"]?", raw_content, re.MULTILINE)
    if remote_dir_match:
        extracted_remote = remote_dir_match.group(1).strip()
        # Resolve any nested variables in remote_dir
        extracted_remote = substitute_env_vars(extracted_remote, env_dict, protect_keys=False)
        env_dict["remote_dir"] = extracted_remote.replace("\\", "/").rstrip("/")

    # Substitute env vars
    resolved_content = substitute_env_vars(raw_content, env_dict)

    try:
        data = yaml.safe_load(resolved_content) or {}
    except yaml.YAMLError as e:
        log_error(f"YAML Syntax Error in '{config_path}':\n{e}")
        sys.exit(1)

    # Global / Default server settings
    global_server = data.get("server") or data.get("vps") or data.get("defaults") or {}

    # Extract services
    # Can be defined under "services:" or directly as top-level keys
    services = {}
    if "services" in data and isinstance(data["services"], dict):
        services = data["services"]
    else:
        reserved_keys = {"server", "vps", "defaults", "env_file", "env", "variables", "vars"}
        for k, v in data.items():
            if k not in reserved_keys and isinstance(v, dict):
                services[k] = v

    if not services:
        log_error(f"No services found in configuration file '{config_path}'.")
        log_info("Please define at least one service (e.g., frontend, backend). Run uhdeploy --example to see syntax.")
        sys.exit(1)

    # Normalize services by merging global server info
    normalized = {}
    for name, s_cfg in services.items():
        if not isinstance(s_cfg, dict):
            continue
        cfg = dict(s_cfg)

        # Merge server details
        srv = dict(global_server)
        srv.update(cfg.get("server") or cfg.get("vps") or cfg.get("target") or {})
        cfg["server"] = srv

        # Detect docker flag
        # Accept 'docker: false', 'dont_use_docker: true', 'use_docker: false', etc.
        docker_raw = cfg.get("docker")
        if docker_raw is None:
            if cfg.get("dont_use_docker") is True or cfg.get("use_docker") is False:
                cfg["docker"] = False
            else:
                cfg["docker"] = False
        normalized[name] = cfg

    return normalized, env_dict


# =============================================================================
# 🧩 DOCKERFILE-STYLE STEP PARSER
# =============================================================================

def parse_step(step_entry):
    """
    Parses a step into a standardized dict:
    - String syntax:
      "RUN npm run build" -> {'action': 'RUN', 'command': 'npm run build'}
      "COPY src dest"     -> {'action': 'COPY', 'src': 'src', 'dest': 'dest'}
      "CMD python app.py" -> {'action': 'CMD', 'command': 'python app.py'}
      "npm run build"     -> {'action': 'RUN', 'command': 'npm run build'}
    - Dict syntax:
      {'run': '...'} or {'copy': '...'} or {'copy': {'src': '...', 'dest': '...'}}
    """
    if isinstance(step_entry, str):
        trimmed = step_entry.strip()
        parts = trimmed.split(None, 1)
        if not parts:
            return None
        verb = parts[0].upper()
        arg = parts[1] if len(parts) > 1 else ""

        if verb in ("RUN", "CMD"):
            return {"action": "RUN", "command": arg}
        elif verb == "COPY":
            # Handles "COPY src dest" or "COPY src -> dest"
            clean_arg = arg.replace("->", " ")
            cparts = clean_arg.split()
            if len(cparts) >= 2:
                return {"action": "COPY", "src": cparts[0], "dest": cparts[1]}
            return {"action": "COPY", "src": arg, "dest": ""}
        elif verb == "WORKDIR":
            return {"action": "WORKDIR", "dir": arg}
        elif verb == "ENV":
            if "=" in arg:
                k, v = arg.split("=", 1)
                return {"action": "ENV", "key": k.strip(), "val": v.strip()}
            return {"action": "ENV", "raw": arg}
        else:
            # Default fallback for arbitrary shell command without "RUN" prefix
            return {"action": "RUN", "command": trimmed}

    elif isinstance(step_entry, dict):
        if "run" in step_entry:
            return {"action": "RUN", "command": str(step_entry["run"])}
        if "cmd" in step_entry:
            return {"action": "RUN", "command": str(step_entry["cmd"])}
        if "copy" in step_entry:
            cval = step_entry["copy"]
            if isinstance(cval, dict):
                return {"action": "COPY", "src": str(cval.get("src", "")), "dest": str(cval.get("dest", ""))}
            elif isinstance(cval, str):
                cparts = cval.replace("->", " ").split()
                if len(cparts) >= 2:
                    return {"action": "COPY", "src": cparts[0], "dest": cparts[1]}
                return {"action": "COPY", "src": cval, "dest": ""}
        if "workdir" in step_entry:
            return {"action": "WORKDIR", "dir": str(step_entry["workdir"])}

    return None

def normalize_steps(step_list):
    """Converts a step list or single step into parsed normalized items."""
    if not step_list:
        return []
    if isinstance(step_list, str):
        step_list = [step_list]
    parsed = []
    for item in step_list:
        res = parse_step(item)
        if res:
            parsed.append(res)
    return parsed


# =============================================================================
# 🚫 FILE & DIRECTORY IGNORE PATTERNS
# =============================================================================

DEFAULT_IGNORES = [
    ".git",
    ".gitignore",
    ".gitattributes",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    "Thumbs.db",
    ".vscode",
    ".idea",
    ".deploy_archive_*.tar.gz",
    ".uhdeploy_*.tar.gz"
]

def is_ignored(name, rel_path, ignore_patterns):
    if not ignore_patterns:
        return False
    norm_name = name.rstrip("/").rstrip("\\")
    norm_rel = rel_path.replace("\\", "/").strip("/")

    for pat in ignore_patterns:
        pat_clean = pat.strip().replace("\\", "/").rstrip("/")
        if not pat_clean or pat_clean.startswith("#"):
            continue
        if pat_clean.startswith("./"):
            pat_clean = pat_clean[2:]
        pat_clean = pat_clean.lstrip("/")

        # Direct basename match (e.g., "node_modules", ".env.local", "*.pyc")
        if fnmatch.fnmatch(norm_name, pat_clean):
            return True
        # Relative path match (e.g., "dist/*", "logs/*.log")
        if fnmatch.fnmatch(norm_rel, pat_clean) or fnmatch.fnmatch(norm_rel, f"*/{pat_clean}"):
            return True
        if fnmatch.fnmatch(norm_rel, f"{pat_clean}/*") or fnmatch.fnmatch(norm_rel, f"*/{pat_clean}/*"):
            return True
    return False


# =============================================================================
# 🔐 SSH & SFTP CLIENT HANDLER
# =============================================================================

class SSHManager:
    def __init__(self, host, user, port=22, key_path=None, passphrase=None, password=None, retries=5):
        self.host = host
        self.user = user or "root"
        self.port = int(port or 22)
        self.key_path = os.path.expanduser(key_path) if key_path else None
        self.passphrase = passphrase
        self.password = password
        self.retries = int(retries or 5)
        self.client = None
        self._created_dirs = set()
        self._reconnect_lock = threading.RLock()
        self._thread_local = threading.local()
        self._active_sftp_clients = []
        self._active_sftp_lock = threading.Lock()

    def connect(self):
        if not paramiko:
            log_error("Paramiko is required for SSH connections. Please run: pip install paramiko")
            sys.exit(1)

        with self._reconnect_lock:
            # Clean up active worker SFTP clients before reconnect
            with self._active_sftp_lock:
                for s in self._active_sftp_clients:
                    try:
                        s.close()
                    except Exception:
                        pass
                self._active_sftp_clients.clear()

            # Close existing client cleanly if any
            if self.client:
                try:
                    self.client.close()
                except Exception:
                    pass
                self.client = None

            log_info(f"Connecting to VPS ({self.user}@{self.host}:{self.port}) via SSH...")
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                "hostname": self.host,
                "port": self.port,
                "username": self.user,
                "timeout": 30,
                "banner_timeout": 60,
                "auth_timeout": 60
            }

            if self.key_path:
                if not os.path.exists(self.key_path):
                    log_error(f"SSH private key file not found: {self.key_path}")
                    sys.exit(1)
                connect_kwargs["key_filename"] = self.key_path
                if self.passphrase:
                    connect_kwargs["passphrase"] = self.passphrase
            elif self.password:
                connect_kwargs["password"] = self.password

            try:
                client.connect(**connect_kwargs)
                transport = client.get_transport()
                if transport:
                    transport.set_keepalive(15)
                self.client = client
                log_success(f"SSH Connection established to {self.host}")
                return self
            except Exception as e:
                log_error(f"Failed to connect to VPS: {e}")
                sys.exit(1)

    def ensure_connected(self):
        """Thread-safe check that SSH transport is active, reconnecting if disconnected."""
        with self._reconnect_lock:
            transport = self.client.get_transport() if self.client else None
            if not self.client or not transport or not transport.is_active():
                self.connect()

    def get_thread_sftp(self):
        """
        Returns an active SFTP client for the calling thread.
        Reuses channels across multiple files without open/close overhead.
        """
        sftp = getattr(self._thread_local, "sftp", None)
        if sftp is not None:
            try:
                chan = sftp.get_channel()
                if chan and chan.is_active():
                    return sftp
            except Exception:
                pass
            self.close_thread_sftp()

        self.ensure_connected()

        with self._reconnect_lock:
            sftp = self.client.open_sftp()

        with self._active_sftp_lock:
            self._active_sftp_clients.append(sftp)

        self._thread_local.sftp = sftp
        return sftp

    def close_thread_sftp(self):
        """Closes the current thread's SFTP client."""
        sftp = getattr(self._thread_local, "sftp", None)
        if sftp is not None:
            try:
                sftp.close()
            except Exception:
                pass
            with self._active_sftp_lock:
                if sftp in self._active_sftp_clients:
                    self._active_sftp_clients.remove(sftp)
            self._thread_local.sftp = None

    def close(self):
        with self._reconnect_lock:
            with self._active_sftp_lock:
                for s in self._active_sftp_clients:
                    try:
                        s.close()
                    except Exception:
                        pass
                self._active_sftp_clients.clear()

            if self.client:
                try:
                    self.client.close()
                except Exception:
                    pass
                self.client = None
            log_info(f"SSH connection to {self.host} closed.")

    def run_cmd(self, cmd, cwd=None, retries=None):
        retries = retries or self.retries
        full_cmd = f"cd '{cwd}' && {cmd}" if cwd else cmd
        log_cmd(full_cmd, kind="VPS SSH")

        for attempt in range(1, retries + 1):
            try:
                self.ensure_connected()
                stdin, stdout, stderr = self.client.exec_command(full_cmd)
                exit_status = stdout.channel.recv_exit_status()

                out = stdout.read().decode("utf-8", errors="replace")
                err = stderr.read().decode("utf-8", errors="replace")

                if out.strip():
                    for line in out.strip().splitlines():
                        print(f"  {Fore.LIGHTBLACK_EX}│{Style.RESET_ALL} {line}")
                if err.strip():
                    for line in err.strip().splitlines():
                        print(f"  {Fore.RED}│{Style.RESET_ALL} {line}", file=sys.stderr)

                if exit_status != 0:
                    log_error(f"Remote command failed with exit status {exit_status}")
                    sys.exit(1)
                return True
            except Exception as e:
                log_warning(f"SSH execution attempt {attempt}/{retries} failed: {e}")
                if attempt == retries:
                    log_error(f"Remote command failed after {retries} attempts.")
                    sys.exit(1)
                time.sleep(min(attempt * 2, 6))
                with self._reconnect_lock:
                    try:
                        self.connect()
                    except Exception:
                        pass

    def mkdir_p(self, remote_dir):
        """Creates directory hierarchy on remote machine via SSH safely."""
        remote_dir_norm = re.sub(r"/+", "/", remote_dir.replace("\\", "/")).rstrip("/")
        if not remote_dir_norm or remote_dir_norm in self._created_dirs:
            return
        try:
            self.ensure_connected()
            stdin, stdout, stderr = self.client.exec_command(f"mkdir -p '{remote_dir_norm}'")
            stdout.channel.recv_exit_status()
            stdout.read()
            stderr.read()
            self._created_dirs.add(remote_dir_norm)
        except Exception:
            pass

    def upload_file(self, local_path, remote_path, retries=None, show_log=True, overwrite=True):
        retries = retries or self.retries
        local_path = os.path.normpath(local_path)
        remote_path = re.sub(r"/+", "/", remote_path.replace("\\", "/"))
        parent_dir = os.path.dirname(remote_path)
        if parent_dir:
            self.mkdir_p(parent_dir)

        base_name = os.path.basename(local_path)
        f_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0

        # Check if remote file exists when overwrite is False (skip existing)
        if not overwrite:
            try:
                sftp = self.get_thread_sftp()
                sftp.stat(remote_path)
                if show_log:
                    print(f"  {Fore.YELLOW}⏭ [SKIPPED]{Style.RESET_ALL} {base_name} (exists on server, overwrite=false)")
                return True
            except (IOError, OSError):
                pass

        for attempt in range(1, retries + 1):
            try:
                sftp = self.get_thread_sftp()

                def progress(transferred, total):
                    if total > 0 and show_log:
                        percent = (transferred / total) * 100
                        mb_trans = transferred / (1024 * 1024)
                        mb_tot = total / (1024 * 1024)
                        sys.stdout.write(f"\r  {Fore.CYAN}📤 [{base_name}] {mb_trans:.1f} MB / {mb_tot:.1f} MB ({percent:.1f}%){Style.RESET_ALL}  ")
                        sys.stdout.flush()

                if attempt == 1 and show_log:
                    print(f"  {Fore.LIGHTBLUE_EX}⇗ Uploading file:{Style.RESET_ALL} {local_path} -> {remote_path}")

                try:
                    sftp.put(local_path, remote_path, callback=progress if f_size > 50000 else None, confirm=False)
                except Exception as put_err:
                    if overwrite:
                        # If put failed and overwrite is enabled, try removing existing remote file first
                        try:
                            sftp.remove(remote_path)
                            sftp.put(local_path, remote_path, callback=progress if f_size > 50000 else None, confirm=False)
                        except Exception:
                            raise put_err
                    else:
                        raise put_err

                if show_log:
                    if f_size > 50000:
                        sys.stdout.write("\n")
                    else:
                        print(f"  {Fore.GREEN}✔ Uploaded:{Style.RESET_ALL} {base_name}")
                return True

            except Exception as e:
                if show_log:
                    sys.stdout.write("\n")
                self.close_thread_sftp()
                log_warning(f"SFTP upload failed for '{base_name}' on attempt {attempt}/{retries}: {e}")

                if attempt >= retries:
                    log_error(f"SFTP upload failed permanently for '{base_name}' after {retries} attempts.")
                    raise e

                time.sleep(min(attempt * 2, 6))
                with self._reconnect_lock:
                    try:
                        log_info(f"Reconnecting SSH to {self.host}...")
                        self.connect()
                    except Exception as re_err:
                        log_warning(f"SSH reconnect failed: {re_err}")

    def upload_archive(self, local_dir, remote_dir, ignore_patterns=None, retries=None, overwrite=True):
        """
        Ultra-fast single-shot archive transfer:
        Packs non-ignored files into a compressed tarball, uploads via SFTP,
        and unpacks on the remote server in seconds. Ideal for 1,000+ files.
        """
        retries = retries or self.retries
        local_dir = os.path.normpath(local_dir)
        remote_dir = re.sub(r"/+", "/", remote_dir.replace("\\", "/")).rstrip("/")
        self.mkdir_p(remote_dir)

        patterns = list(DEFAULT_IGNORES)
        if ignore_patterns:
            patterns.extend(ignore_patterns)

        print(f"  {Fore.LIGHTBLUE_EX}📦 [ARCHIVE SYNC] Packaging directory for fast upload:{Style.RESET_ALL} {local_dir}")
        start_pack = time.time()

        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp_tar:
            tmp_tar_path = tmp_tar.name

        try:
            file_count = 0
            with tarfile.open(tmp_tar_path, "w:gz") as tar:
                for root, dirs, files in os.walk(local_dir):
                    rel_dir = os.path.relpath(root, local_dir).replace("\\", "/")
                    dirs[:] = [
                        d for d in dirs
                        if not is_ignored(d, d if rel_dir == "." else f"{rel_dir}/{d}", patterns)
                    ]
                    for f in files:
                        rel_file = f if rel_dir == "." else f"{rel_dir}/{f}"
                        if is_ignored(f, rel_file, patterns):
                            continue
                        full_local = os.path.join(root, f)
                        tar.add(full_local, arcname=rel_file)
                        file_count += 1

            tar_size = os.path.getsize(tmp_tar_path)
            tar_mb = tar_size / (1024 * 1024)
            pack_time = time.time() - start_pack
            log_info(f"Packaged {file_count} files into {tar_mb:.2f} MB archive in {pack_time:.2f}s.")

            remote_tar_name = f".uhdeploy_{int(time.time())}.tar.gz"
            remote_tar_path = f"{remote_dir}/{remote_tar_name}"
            log_step("SFTP", "TRANSFER", f"Transferring compressed archive ({tar_mb:.2f} MB)...")
            self.upload_file(tmp_tar_path, remote_tar_path, retries=retries, show_log=True, overwrite=True)

            tar_flag = "--overwrite" if overwrite else "--skip-old-files"
            step_desc = "Extracting & overwriting" if overwrite else "Extracting (skipping existing)"
            log_step("VPS", "EXTRACT", f"{step_desc} {file_count} files into {remote_dir}...")
            self.run_cmd(f"tar -xzf '{remote_tar_path}' {tar_flag} -C '{remote_dir}' && rm -f '{remote_tar_path}'")
            log_success(f"Fast archive sync completed: {file_count} files processed successfully.")
        finally:
            if os.path.exists(tmp_tar_path):
                try:
                    os.remove(tmp_tar_path)
                except Exception:
                    pass

    def upload_directory(self, local_dir, remote_dir, ignore_patterns=None, max_workers=8, retries=None, overwrite=True):
        retries = retries or self.retries
        local_dir = os.path.normpath(local_dir)
        remote_dir = re.sub(r"/+", "/", remote_dir.replace("\\", "/")).rstrip("/")
        self.mkdir_p(remote_dir)

        patterns = list(DEFAULT_IGNORES)
        if ignore_patterns:
            patterns.extend(ignore_patterns)

        # 1. Collect files to upload
        file_pairs = []
        total_bytes = 0
        for root, dirs, files in os.walk(local_dir):
            rel_dir = os.path.relpath(root, local_dir).replace("\\", "/")
            dirs[:] = [
                d for d in dirs
                if not is_ignored(d, d if rel_dir == "." else f"{rel_dir}/{d}", patterns)
            ]
            target_sub = remote_dir if rel_dir == "." else f"{remote_dir}/{rel_dir}"

            for f in files:
                rel_file = f if rel_dir == "." else f"{rel_dir}/{f}"
                if is_ignored(f, rel_file, patterns):
                    continue
                l_file = os.path.join(root, f)
                r_file = f"{target_sub}/{f}"
                f_size = os.path.getsize(l_file) if os.path.exists(l_file) else 0
                file_pairs.append((l_file, r_file, rel_file, f_size))
                total_bytes += f_size

        total_files = len(file_pairs)
        if total_files == 0:
            log_info("No files to upload (empty directory or all ignored).")
            return

        total_mb = total_bytes / (1024 * 1024)
        overwrite_info = "overwrite: ON" if overwrite else "overwrite: OFF (skip existing)"
        print(f"  {Fore.LIGHTBLUE_EX}⇗ Syncing directory:{Style.RESET_ALL} {local_dir} -> {remote_dir}")
        print(f"    {Fore.CYAN}ℹ️  {total_files} file(s) ({total_mb:.2f} MB) queued [{overwrite_info}] using {max_workers} worker threads...{Style.RESET_ALL}")

        # 2. Batch create all remote directories in chunks to save network roundtrips
        distinct_dirs = sorted(list({os.path.dirname(r) for _, r, _, _ in file_pairs if os.path.dirname(r)}))
        to_create = [d for d in distinct_dirs if d not in self._created_dirs]
        if to_create:
            chunk_size = 50
            for i in range(0, len(to_create), chunk_size):
                chunk = to_create[i:i + chunk_size]
                dirs_arg = " ".join(f"'{d}'" for d in chunk)
                try:
                    self.ensure_connected()
                    stdin, stdout, stderr = self.client.exec_command(f"mkdir -p {dirs_arg}")
                    stdout.channel.recv_exit_status()
                    for d in chunk:
                        self._created_dirs.add(d)
                except Exception:
                    pass

        # 3. Thread-safe worker task
        completed_count = 0
        skipped_count = 0
        uploaded_bytes = 0
        progress_lock = threading.Lock()
        start_time = time.time()

        def worker_task(item):
            nonlocal completed_count, skipped_count, uploaded_bytes
            l_file, r_file, rel_file, f_size = item

            # If overwrite is False, check if remote file already exists
            if not overwrite:
                try:
                    sftp = self.get_thread_sftp()
                    sftp.stat(r_file)
                    with progress_lock:
                        skipped_count += 1
                        completed_count += 1
                        pct = (completed_count / total_files) * 100
                        disp_name = rel_file if len(rel_file) <= 40 else "..." + rel_file[-37:]
                        sys.stdout.write(
                            f"\r  {Fore.YELLOW}⏭ [{completed_count}/{total_files}] ({pct:.1f}%) [SKIPPED] - {Fore.WHITE}{disp_name:<40}{Style.RESET_ALL}  "
                        )
                        sys.stdout.flush()
                    return
                except (IOError, OSError):
                    pass

            last_err = None
            for attempt in range(1, retries + 1):
                try:
                    sftp = self.get_thread_sftp()
                    try:
                        sftp.put(l_file, r_file, confirm=False)
                    except Exception as put_err:
                        if overwrite:
                            try:
                                sftp.remove(r_file)
                                sftp.put(l_file, r_file, confirm=False)
                            except Exception:
                                raise put_err
                        else:
                            raise put_err
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    self.close_thread_sftp()
                    with progress_lock:
                        log_warning(f"Upload failed for '{rel_file}' (Attempt {attempt}/{retries}): {e}")
                    if attempt >= retries:
                        break
                    time.sleep(min(attempt * 2, 6))
                    try:
                        self.ensure_connected()
                    except Exception:
                        pass

            if last_err:
                raise last_err

            with progress_lock:
                completed_count += 1
                uploaded_bytes += f_size
                pct = (completed_count / total_files) * 100
                mb_done = uploaded_bytes / (1024 * 1024)
                disp_name = rel_file if len(rel_file) <= 40 else "..." + rel_file[-37:]
                sys.stdout.write(
                    f"\r  {Fore.CYAN}📤 [{completed_count}/{total_files}] ({pct:.1f}%) {mb_done:.1f}/{total_mb:.1f} MB - {Fore.WHITE}{disp_name:<40}{Style.RESET_ALL}  "
                )
                sys.stdout.flush()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(worker_task, item) for item in file_pairs]
            for future in concurrent.futures.as_completed(futures):
                future.result()

        # Clean up thread-local SFTP channels
        with self._active_sftp_lock:
            for s in self._active_sftp_clients:
                try:
                    s.close()
                except Exception:
                    pass
            self._active_sftp_clients.clear()

        elapsed = time.time() - start_time
        speed = (total_mb / elapsed) if elapsed > 0 else 0
        sys.stdout.write("\n")
        transferred_count = completed_count - skipped_count
        if skipped_count > 0:
            log_success(f"Transferred {transferred_count} file(s), skipped {skipped_count} existing file(s) ({total_mb:.2f} MB) in {elapsed:.1f}s using {max_workers} threads.")
        else:
            log_success(f"Transferred {total_files} file(s) ({total_mb:.2f} MB) in {elapsed:.1f}s ({speed:.2f} MB/s) using {max_workers} threads.")


# =============================================================================
# 📡 FTP CLIENT HANDLER (Standard Library ftplib with Multi-Threading)
# =============================================================================

class FTPManager:
    def __init__(self, host, user, port=21, password=None, retries=5):
        self.host = host
        self.user = user or "anonymous"
        self.port = int(port or 21)
        self.password = password or ""
        self.retries = int(retries or 5)
        self.ftp = None
        self._thread_local = threading.local()
        self._active_connections = []
        self._active_conn_lock = threading.Lock()
        self._created_dirs = set()

    def _create_connection(self, retries=None):
        retries = retries or self.retries
        for attempt in range(1, retries + 1):
            try:
                ftp = ftplib.FTP()
                ftp.connect(self.host, self.port, timeout=30)
                ftp.login(self.user, self.password)
                return ftp
            except Exception as e:
                if attempt >= retries:
                    raise e
                time.sleep(min(attempt * 2, 6))

    def connect(self):
        log_info(f"Connecting to VPS ({self.user}@{self.host}:{self.port}) via FTP...")
        try:
            self.ftp = self._create_connection()
            log_success(f"FTP Connection established to {self.host}")
            return self
        except Exception as e:
            log_error(f"Failed to connect to FTP server: {e}")
            sys.exit(1)

    def get_thread_ftp(self, retries=None):
        ftp = getattr(self._thread_local, "ftp", None)
        if ftp is not None:
            try:
                ftp.voidcmd("NOOP")
                return ftp
            except Exception:
                pass
            self.close_thread_ftp()

        ftp = self._create_connection(retries)
        with self._active_conn_lock:
            self._active_connections.append(ftp)
        self._thread_local.ftp = ftp
        return ftp

    def close_thread_ftp(self):
        ftp = getattr(self._thread_local, "ftp", None)
        if ftp:
            try:
                ftp.quit()
            except Exception:
                try:
                    ftp.close()
                except Exception:
                    pass
            with self._active_conn_lock:
                if ftp in self._active_connections:
                    self._active_connections.remove(ftp)
            self._thread_local.ftp = None

    def close(self):
        with self._active_conn_lock:
            for conn in self._active_connections:
                try:
                    conn.quit()
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
            self._active_connections.clear()

        if self.ftp:
            try:
                self.ftp.quit()
            except Exception:
                try:
                    self.ftp.close()
                except Exception:
                    pass
            self.ftp = None
        log_info(f"FTP connection to {self.host} closed.")

    def run_cmd(self, cmd, cwd=None):
        log_warning(f"[FTP Limitation] Cannot run remote command: '{cmd}'. FTP protocol does not support shell execution!")
        log_info("Only file transfers are supported over FTP. Use SSH for remote commands/Docker.")
        return False

    def mkdir_p(self, remote_dir):
        """Recursively ensures remote directories exist on FTP."""
        remote_dir = remote_dir.replace("\\", "/").strip("/")
        if not remote_dir or remote_dir in self._created_dirs:
            return
        parts = remote_dir.split("/")
        current = ""
        for p in parts:
            current += "/" + p
            if current in self._created_dirs:
                continue
            try:
                self.ftp.cwd(current)
                self._created_dirs.add(current)
            except ftplib.error_perm:
                try:
                    self.ftp.mkd(current)
                    self._created_dirs.add(current)
                except Exception:
                    pass

    def upload_file(self, local_path, remote_path, retries=None, show_log=True, overwrite=True):
        retries = retries or self.retries
        local_path = os.path.normpath(local_path)
        remote_path = re.sub(r"/+", "/", remote_path.replace("\\", "/"))
        parent_dir = os.path.dirname(remote_path)
        if parent_dir:
            self.mkdir_p(parent_dir)

        base_name = os.path.basename(local_path)

        # Check if remote file exists when overwrite is False
        if not overwrite:
            try:
                ftp = self.get_thread_ftp(retries)
                if ftp.size(remote_path) is not None:
                    if show_log:
                        print(f"  {Fore.YELLOW}⏭ [FTP SKIPPED]{Style.RESET_ALL} {base_name} (exists on server, overwrite=false)")
                    return True
            except Exception:
                pass

        for attempt in range(1, retries + 1):
            try:
                ftp = self.get_thread_ftp(retries)
                if attempt == 1 and show_log:
                    print(f"  {Fore.LIGHTBLUE_EX}⇗ [FTP] Uploading:{Style.RESET_ALL} {local_path} -> {remote_path}")
                try:
                    with open(local_path, "rb") as f:
                        ftp.storbinary(f"STOR {remote_path}", f)
                    return True
                except Exception as put_err:
                    if overwrite:
                        try:
                            ftp.delete(remote_path)
                            with open(local_path, "rb") as f:
                                ftp.storbinary(f"STOR {remote_path}", f)
                            return True
                        except Exception:
                            raise put_err
                    else:
                        raise put_err
            except Exception as e:
                self.close_thread_ftp()
                log_warning(f"FTP upload failed for '{base_name}' on attempt {attempt}/{retries}: {e}")
                if attempt >= retries:
                    log_error(f"FTP upload failed permanently after {retries} attempts.")
                    raise e
                time.sleep(min(attempt * 2, 6))

    def upload_directory(self, local_dir, remote_dir, ignore_patterns=None, max_workers=4, retries=None, overwrite=True):
        retries = retries or self.retries
        local_dir = os.path.normpath(local_dir)
        remote_dir = re.sub(r"/+", "/", remote_dir.replace("\\", "/")).rstrip("/")
        self.mkdir_p(remote_dir)

        patterns = list(DEFAULT_IGNORES)
        if ignore_patterns:
            patterns.extend(ignore_patterns)

        file_pairs = []
        total_bytes = 0
        for root, dirs, files in os.walk(local_dir):
            rel_dir = os.path.relpath(root, local_dir).replace("\\", "/")
            dirs[:] = [
                d for d in dirs
                if not is_ignored(d, d if rel_dir == "." else f"{rel_dir}/{d}", patterns)
            ]
            target_sub = remote_dir if rel_dir == "." else f"{remote_dir}/{rel_dir}"

            for f in files:
                rel_file = f if rel_dir == "." else f"{rel_dir}/{f}"
                if is_ignored(f, rel_file, patterns):
                    continue
                l_file = os.path.join(root, f)
                r_file = f"{target_sub}/{f}"
                f_size = os.path.getsize(l_file) if os.path.exists(l_file) else 0
                file_pairs.append((l_file, r_file, rel_file, f_size))
                total_bytes += f_size

        total_files = len(file_pairs)
        if total_files == 0:
            log_info("No files to upload (empty directory or all ignored).")
            return

        total_mb = total_bytes / (1024 * 1024)
        overwrite_info = "overwrite: ON" if overwrite else "overwrite: OFF (skip existing)"
        print(f"  {Fore.LIGHTBLUE_EX}⇗ [FTP] Syncing directory:{Style.RESET_ALL} {local_dir} -> {remote_dir}")
        print(f"    {Fore.CYAN}ℹ️  {total_files} file(s) ({total_mb:.2f} MB) queued [{overwrite_info}] using {max_workers} worker threads...{Style.RESET_ALL}")

        # Ensure parent directories exist
        distinct_dirs = sorted(list({os.path.dirname(r) for _, r, _, _ in file_pairs if os.path.dirname(r)}))
        for d in distinct_dirs:
            self.mkdir_p(d)

        completed_count = 0
        skipped_count = 0
        uploaded_bytes = 0
        progress_lock = threading.Lock()
        start_time = time.time()

        def worker_task(item):
            nonlocal completed_count, skipped_count, uploaded_bytes
            l_file, r_file, rel_file, f_size = item

            # If overwrite is False, check if remote file exists first
            if not overwrite:
                try:
                    ftp = self.get_thread_ftp(retries)
                    if ftp.size(r_file) is not None:
                        with progress_lock:
                            skipped_count += 1
                            completed_count += 1
                            pct = (completed_count / total_files) * 100
                            disp_name = rel_file if len(rel_file) <= 40 else "..." + rel_file[-37:]
                            sys.stdout.write(
                                f"\r  {Fore.YELLOW}⏭ [FTP SKIPPED] [{completed_count}/{total_files}] ({pct:.1f}%) - {Fore.WHITE}{disp_name:<40}{Style.RESET_ALL}  "
                            )
                            sys.stdout.flush()
                        return
                except Exception:
                    pass

            last_err = None
            for attempt in range(1, retries + 1):
                try:
                    ftp = self.get_thread_ftp(retries)
                    try:
                        with open(l_file, "rb") as f:
                            ftp.storbinary(f"STOR {r_file}", f)
                    except Exception as put_err:
                        if overwrite:
                            try:
                                ftp.delete(r_file)
                                with open(l_file, "rb") as f:
                                    ftp.storbinary(f"STOR {r_file}", f)
                            except Exception:
                                raise put_err
                        else:
                            raise put_err
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    self.close_thread_ftp()
                    with progress_lock:
                        log_warning(f"FTP upload failed for '{rel_file}' (Attempt {attempt}/{retries}): {e}")
                    if attempt >= retries:
                        break
                    time.sleep(min(attempt * 2, 6))

            if last_err:
                raise last_err

            with progress_lock:
                completed_count += 1
                uploaded_bytes += f_size
                pct = (completed_count / total_files) * 100
                mb_done = uploaded_bytes / (1024 * 1024)
                disp_name = rel_file if len(rel_file) <= 40 else "..." + rel_file[-37:]
                sys.stdout.write(
                    f"\r  {Fore.CYAN}📤 [FTP] [{completed_count}/{total_files}] ({pct:.1f}%) {mb_done:.1f}/{total_mb:.1f} MB - {Fore.WHITE}{disp_name:<40}{Style.RESET_ALL}  "
                )
                sys.stdout.flush()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(worker_task, item) for item in file_pairs]
            for future in concurrent.futures.as_completed(futures):
                future.result()

        with self._active_conn_lock:
            for conn in self._active_connections:
                try:
                    conn.quit()
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
            self._active_connections.clear()

        elapsed = time.time() - start_time
        speed = (total_mb / elapsed) if elapsed > 0 else 0
        sys.stdout.write("\n")
        transferred_count = completed_count - skipped_count
        if skipped_count > 0:
            log_success(f"FTP Transferred {transferred_count} file(s), skipped {skipped_count} existing file(s) ({total_mb:.2f} MB) in {elapsed:.1f}s using {max_workers} threads.")
        else:
            log_success(f"FTP Transferred {total_files} file(s) ({total_mb:.2f} MB) in {elapsed:.1f}s ({speed:.2f} MB/s) using {max_workers} threads.")


# =============================================================================
# ⚙️ LOCAL COMMAND & BUILD RUNNER
# =============================================================================

def run_local_cmd(cmd, cwd=None):
    log_cmd(cmd, kind="LOCAL")
    res = subprocess.run(cmd, shell=True, cwd=cwd)
    if res.returncode != 0:
        log_error(f"Local command failed with exit code {res.returncode}: '{cmd}'")
        sys.exit(1)

def run_local_copy(src, dest, cwd=None):
    src_path = os.path.join(cwd, src) if cwd and not os.path.isabs(src) else src
    dest_path = os.path.join(cwd, dest) if cwd and not os.path.isabs(dest) else dest

    if not os.path.exists(src_path):
        log_error(f"Source file/folder for COPY not found: '{src_path}'")
        sys.exit(1)

    print(f"  {Fore.LIGHTBLUE_EX}📋 [LOCAL COPY]{Style.RESET_ALL} {src} -> {dest}")
    dest_dir = os.path.dirname(dest_path) if not os.path.isdir(dest_path) else dest_path
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)

    if os.path.isdir(src_path):
        shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
    else:
        shutil.copy2(src_path, dest_path)


# =============================================================================
# 🚀 SERVICE DEPLOYMENT ORCHESTRATOR
# =============================================================================

def deploy_service(name, cfg, project_root, dry_run=False, cli_threads=None, cli_retries=None, cli_archive=None, cli_overwrite=None):
    print_separator("═", 75, Fore.CYAN)
    log_step(name, "STARTING", cfg.get("description", f"Deploying service '{name}'"))

    # 1. Resolve work directory
    rel_work_dir = cfg.get("work_dir") or cfg.get("working_dir") or "."
    work_dir = os.path.abspath(os.path.join(project_root, rel_work_dir))
    log_info(f"Local Working Directory: {Fore.WHITE}{work_dir}")

    server_cfg = cfg.get("server", {})
    proto = str(server_cfg.get("type", "ssh")).lower().strip()
    host = server_cfg.get("host") or server_cfg.get("ip")
    user = server_cfg.get("user") or server_cfg.get("username", "root")
    port = server_cfg.get("port") or (21 if proto == "ftp" else 22)
    remote_base = (server_cfg.get("remote_dir") or server_cfg.get("path") or f"/opt/{name}").replace("\\", "/").rstrip("/")

    # Resolve concurrency, retry, archive, and overwrite options
    threads = cli_threads or cfg.get("threads") or server_cfg.get("threads") or 8
    retries = cli_retries or cfg.get("retries") or server_cfg.get("retries") or 5
    use_archive = cli_archive if cli_archive is not None else bool(cfg.get("archive") or cfg.get("fast_sync") or server_cfg.get("archive") or False)

    # Overwrite behavior: True by default. Can be set to False via --no-overwrite or overwrite: false in deploy.yml
    if cli_overwrite is not None:
        overwrite = cli_overwrite
    elif cfg.get("overwrite") is not None:
        overwrite = bool(cfg.get("overwrite"))
    elif server_cfg.get("overwrite") is not None:
        overwrite = bool(server_cfg.get("overwrite"))
    elif cfg.get("skip_existing") is True or server_cfg.get("skip_existing") is True:
        overwrite = False
    else:
        overwrite = True

    # Check connection requirements
    if not dry_run and not host:
        log_error(f"No VPS host specified for service '{name}'! Set server.host in deploy.yml or VPS_IP in .env.")
        sys.exit(1)

    mode_info = f"Archive Mode" if (use_archive and proto == "ssh") else f"{threads} Threads"
    overwrite_str = "Overwrite: ON" if overwrite else "Overwrite: OFF (Skip Existing)"
    log_info(f"Target Server: {Fore.WHITE}{user}@{host}:{port} ({proto.upper()}) | Remote Dir: {remote_base} | Mode: {mode_info} | {overwrite_str} (Retries: {retries})")

    # Resolve ignore patterns early
    ignore_list = list(DEFAULT_IGNORES)
    custom_ignores = cfg.get("ignore") or cfg.get("exclude") or []
    if isinstance(custom_ignores, str):
        custom_ignores = [custom_ignores]
    ignore_list.extend(custom_ignores)

    # Check for .deployignore in work_dir or project_root
    for cand_dir in [work_dir, project_root]:
        dep_ign = os.path.join(cand_dir, ".deployignore")
        if os.path.isfile(dep_ign):
            try:
                with open(dep_ign, "r", encoding="utf-8", errors="replace") as dif:
                    for line in dif:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            ignore_list.append(line)
            except Exception:
                pass
            break

    # Parse pre-deploy and post-deploy steps
    before_steps = normalize_steps(cfg.get("before_deploy") or cfg.get("pre_deploy") or cfg.get("before_run"))
    remote_steps = normalize_steps(cfg.get("run_in_vps") or cfg.get("after_deploy") or cfg.get("post_deploy"))

    # Docker configuration
    docker_cfg = cfg.get("docker")
    is_docker = False
    if isinstance(docker_cfg, dict):
        is_docker = docker_cfg.get("enabled", True)
    elif isinstance(docker_cfg, bool):
        is_docker = docker_cfg

    # Non-Docker upload list
    upload_list = cfg.get("upload") or []
    if isinstance(upload_list, str):
        upload_list = [upload_list]
    if not upload_list and not is_docker:
        candidate_dist = os.path.join(work_dir, "dist")
        if os.path.isdir(candidate_dist):
            upload_list.append(f"dist/ -> {remote_base}")
        else:
            upload_list.append(f". -> {remote_base}")

    # 2. Local Build Phase
    build_steps = normalize_steps(cfg.get("build") or cfg.get("for_build") or cfg.get("build_steps"))
    if build_steps:
        print_separator("─", 50, Fore.MAGENTA)
        log_step(name, "LOCAL BUILD", f"Executing {len(build_steps)} build step(s)...")
        for s in build_steps:
            if dry_run:
                print(f"  {Fore.YELLOW}[DRY-RUN BUILD]{Style.RESET_ALL} {s}")
                continue

            action = s["action"]
            if action in ("RUN", "CMD"):
                run_local_cmd(s["command"], cwd=work_dir)
            elif action == "COPY":
                run_local_copy(s["src"], s["dest"], cwd=work_dir)
            elif action == "WORKDIR":
                work_dir = os.path.abspath(os.path.join(work_dir, s["dir"]))
                log_info(f"Changed local working dir to: {work_dir}")

    # Dry-run full simulation mode
    if dry_run:
        # Pre-deploy simulation
        if before_steps:
            print_separator("─", 50, Fore.MAGENTA)
            log_step(name, "PRE-DEPLOY [DRY-RUN]", f"Simulating {len(before_steps)} pre-deploy step(s)...")
            for s in before_steps:
                if s["action"] in ("RUN", "CMD"):
                    cmd = s["command"].replace("${remote_dir}", remote_base).replace("$remote_dir", remote_base)
                    print(f"  {Fore.YELLOW}[DRY-RUN VPS CMD]{Style.RESET_ALL} {cmd}")
                elif s["action"] == "COPY":
                    local_src = os.path.normpath(os.path.join(project_root, s["src"]) if not os.path.isabs(s["src"]) else s["src"])
                    remote_dst = s["dest"].replace("${remote_dir}", remote_base).replace("$remote_dir", remote_base)
                    if not remote_dst.startswith("/"):
                        remote_dst = f"{remote_base}/{remote_dst}"
                    remote_dst = re.sub(r"/+", "/", remote_dst).rstrip("/")
                    print(f"  {Fore.YELLOW}[DRY-RUN SFTP COPY]{Style.RESET_ALL} {local_src} -> {remote_dst}")

        # Deploy simulation
        if is_docker:
            print_separator("─", 50, Fore.MAGENTA)
            log_step(name, "DOCKER [DRY-RUN]", "Simulating Docker container deployment...")
            d_dict = docker_cfg if isinstance(docker_cfg, dict) else {}
            s_name = d_dict.get("service_name") or d_dict.get("service") or name
            img = d_dict.get("image") or f"{name}:latest"
            print(f"  {Fore.YELLOW}[DRY-RUN DOCKER]{Style.RESET_ALL} Service: {s_name} | Image: {img}")
        else:
            print_separator("─", 50, Fore.MAGENTA)
            log_step(name, "UPLOAD [DRY-RUN]", "Simulating file uploads and target destinations...")
            for up in upload_list:
                src, dst = "", ""
                if isinstance(up, dict):
                    src, dst = up.get("src", ""), up.get("dest", "")
                elif isinstance(up, str):
                    parts = up.replace("->", " ").split()
                    src, dst = (parts[0], parts[1]) if len(parts) >= 2 else (parts[0], remote_base)

                dst = dst.replace("${remote_dir}", remote_base).replace("$remote_dir", remote_base)
                if not dst.startswith("/"):
                    dst = f"{remote_base}/{dst}"
                dst = re.sub(r"/+", "/", dst).rstrip("/")

                local_full = os.path.normpath(os.path.join(work_dir, src) if not os.path.isabs(src) else src)
                if os.path.isdir(local_full):
                    match_count = 0
                    for root, dirs, files in os.walk(local_full):
                        rel_d = os.path.relpath(root, local_full).replace("\\", "/")
                        dirs[:] = [d for d in dirs if not is_ignored(d, d if rel_d == "." else f"{rel_d}/{d}", ignore_list)]
                        for f in files:
                            rel_f = f if rel_d == "." else f"{rel_d}/{f}"
                            if not is_ignored(f, rel_f, ignore_list):
                                match_count += 1
                    mode_label = "Archive (1-shot tarball)" if (use_archive and proto == "ssh") else f"Multi-threaded ({threads} threads)"
                    overwrite_label = "Overwrite: ON" if overwrite else "Overwrite: OFF (Skip Existing)"
                    print(f"  {Fore.YELLOW}[DRY-RUN SYNC DIR]{Style.RESET_ALL} {local_full} -> {dst}")
                    print(f"    {Fore.CYAN}ℹ️  {match_count} files would be uploaded [{mode_label}, {overwrite_label}, Retries: {retries}]{Style.RESET_ALL} (ignoring: {', '.join(custom_ignores[:5])})")
                elif os.path.isfile(local_full):
                    overwrite_label = "Overwrite: ON" if overwrite else "Overwrite: OFF (Skip Existing)"
                    print(f"  {Fore.YELLOW}[DRY-RUN UPLOAD FILE]{Style.RESET_ALL} {local_full} -> {dst} [{overwrite_label}]")

        # Post-deploy simulation
        if remote_steps:
            print_separator("─", 50, Fore.MAGENTA)
            log_step(name, "RUN IN VPS [DRY-RUN]", f"Simulating {len(remote_steps)} remote command(s)...")
            for s in remote_steps:
                if s["action"] in ("RUN", "CMD"):
                    cmd = s["command"].replace("${remote_dir}", remote_base).replace("$remote_dir", remote_base)
                    print(f"  {Fore.YELLOW}[DRY-RUN VPS CMD]{Style.RESET_ALL} {cmd}")

        log_success(f"[DRY-RUN] Finished simulating deployment for '{name}'.")
        return

    # 3. Establish Connection to VPS
    conn = None
    if proto == "ftp":
        conn = FTPManager(
            host=host,
            user=user,
            port=port,
            password=server_cfg.get("password"),
            retries=retries
        ).connect()
    else: # Default: SSH
        conn = SSHManager(
            host=host,
            user=user,
            port=port,
            key_path=server_cfg.get("key_path"),
            passphrase=server_cfg.get("passphrase"),
            password=server_cfg.get("password"),
            retries=retries
        ).connect()

    try:
        # Ensure remote base directory exists
        conn.mkdir_p(remote_base)

        # Pre-deploy commands / remote preparations
        if before_steps:
            print_separator("─", 50, Fore.MAGENTA)
            log_step(name, "PRE-DEPLOY", f"Running {len(before_steps)} pre-deploy step(s) on VPS...")
            for s in before_steps:
                action = s["action"]
                if action in ("RUN", "CMD"):
                    cmd = s["command"].replace("${remote_dir}", remote_base).replace("$remote_dir", remote_base)
                    conn.run_cmd(cmd, cwd=remote_base)
                elif action == "COPY":
                    local_src = os.path.normpath(os.path.join(project_root, s["src"]) if not os.path.isabs(s["src"]) else s["src"])
                    remote_dst = s["dest"].replace("${remote_dir}", remote_base).replace("$remote_dir", remote_base)
                    if not remote_dst.startswith("/"):
                        remote_dst = f"{remote_base}/{remote_dst}"
                    remote_dst = re.sub(r"/+", "/", remote_dst).rstrip("/")
                    if os.path.isdir(local_src):
                        if use_archive and proto == "ssh":
                            conn.upload_archive(local_src, remote_dst, ignore_patterns=ignore_list, retries=retries, overwrite=overwrite)
                        else:
                            conn.upload_directory(local_src, remote_dst, ignore_patterns=ignore_list, max_workers=threads, retries=retries, overwrite=overwrite)
                    elif os.path.isfile(local_src):
                        conn.upload_file(local_src, remote_dst, retries=retries, overwrite=overwrite)

        # 4. Handle Docker OR Non-Docker Deployments
        if is_docker:
            if proto == "ftp":
                log_warning("⚠️ Docker deployments require SSH for execution. Over FTP, container commands cannot run.")

            print_separator("─", 50, Fore.MAGENTA)
            log_step(name, "DOCKER DEPLOY", "Deploying with Docker...")

            d_dict = docker_cfg if isinstance(docker_cfg, dict) else {}
            compose_rel = d_dict.get("compose_file") or "docker-compose.yml"
            compose_path = os.path.join(project_root, compose_rel)
            service_name = d_dict.get("service_name") or d_dict.get("service") or name
            image_name = d_dict.get("image") or f"{name}:latest"
            context_rel = d_dict.get("context") or rel_work_dir
            context_dir = os.path.join(project_root, context_rel)
            build_mode = d_dict.get("build_mode", "local").lower() # 'local' (tarball) or 'remote'

            # 4.1 Sync docker-compose.yml to VPS if present
            if os.path.isfile(compose_path):
                log_info(f"Syncing docker-compose file: {compose_rel} -> {remote_base}/docker-compose.yml")
                conn.upload_file(compose_path, f"{remote_base}/docker-compose.yml")

                # Auto-detect and sync referenced env_file(s) from docker-compose.yml or config
                compose_dir = os.path.dirname(compose_path) or project_root
                env_files_to_sync = set()

                # Explicit env files from deploy.yml
                explicit_envs = d_dict.get("env_file") or d_dict.get("env_files") or []
                if isinstance(explicit_envs, str):
                    explicit_envs = [explicit_envs]
                for ee in explicit_envs:
                    env_files_to_sync.add(ee)

                # Auto-parse from docker-compose.yml
                try:
                    with open(compose_path, "r", encoding="utf-8", errors="replace") as cf:
                        compose_data = yaml.safe_load(cf) or {}
                    if isinstance(compose_data, dict):
                        services_dict = compose_data.get("services", {})
                        if isinstance(services_dict, dict):
                            for _, s_def in services_dict.items():
                                if isinstance(s_def, dict) and "env_file" in s_def:
                                    ef = s_def["env_file"]
                                    if isinstance(ef, str):
                                        env_files_to_sync.add(ef)
                                    elif isinstance(ef, list):
                                        for item in ef:
                                            if isinstance(item, str):
                                                env_files_to_sync.add(item)
                                            elif isinstance(item, dict) and "path" in item:
                                                env_files_to_sync.add(item["path"])
                except Exception as e:
                    log_warning(f"Could not parse docker-compose.yml for env_files: {e}")

                # Sync compose dir root .env if it exists and not yet added
                root_env = os.path.join(compose_dir, ".env")
                if os.path.isfile(root_env) and not explicit_envs:
                    env_files_to_sync.add(".env")

                # Upload all discovered env files
                for ef in sorted(env_files_to_sync):
                    clean_ef = ef.replace("\\", "/").strip("/")
                    # Handle paths that start with ./
                    search_rel = clean_ef[2:] if clean_ef.startswith("./") else clean_ef

                    candidate_paths = [
                        os.path.join(compose_dir, search_rel),
                        os.path.join(project_root, search_rel),
                        os.path.join(work_dir, search_rel),
                        os.path.join(compose_dir, os.path.basename(search_rel)),
                        os.path.join(project_root, os.path.basename(search_rel))
                    ]
                    found_local = None
                    for cp in candidate_paths:
                        if os.path.isfile(cp):
                            found_local = cp
                            break

                    if found_local:
                        remote_env_dest = f"{remote_base}/{search_rel}".replace("\\", "/")
                        log_info(f"Syncing compose env file: {search_rel} -> {remote_env_dest}")
                        conn.upload_file(found_local, remote_env_dest)
                    else:
                        log_warning(f"Environment file '{ef}' referenced by docker-compose was not found locally.")

            if build_mode == "local":
                # Build locally, package as tarball, transfer, load into remote Docker
                tar_name = f"{service_name}.tar"
                local_tar_path = os.path.join(project_root, tar_name)
                remote_tar_path = f"{remote_base}/{tar_name}"

                log_step(name, "DOCKER BUILD", f"Building image locally: {image_name}...")
                dockerfile_arg = f"-f {d_dict['dockerfile']}" if d_dict.get("dockerfile") else ""
                run_local_cmd(f"docker build {dockerfile_arg} -t {image_name} {context_dir}")

                log_step(name, "DOCKER SAVE", f"Saving image to archive: {tar_name}...")
                run_local_cmd(f"docker save -o {local_tar_path} {image_name}")

                log_step(name, "SFTP UPLOAD", f"Uploading image archive to VPS...")
                conn.upload_file(local_tar_path, remote_tar_path)

                if proto == "ssh":
                    log_step(name, "DOCKER LOAD", f"Loading image into Docker daemon on VPS...")
                    conn.run_cmd(f"docker load -i {remote_tar_path}")
                    conn.run_cmd(f"rm -f {remote_tar_path}")

                # Clean up local archive
                if os.path.exists(local_tar_path):
                    os.remove(local_tar_path)
                    log_info(f"Cleaned up local archive: {tar_name}")

            else: # 'remote' build mode
                if proto == "ssh":
                    log_step(name, "DOCKER BUILD REMOTE", f"Building service {service_name} directly on VPS...")
                    conn.run_cmd(f"docker compose build {service_name}", cwd=remote_base)

            # Recreate container on VPS
            if proto == "ssh":
                log_step(name, "DOCKER RESTART", f"Starting container(s) on VPS...")
                conn.run_cmd(f"docker compose up -d {service_name}", cwd=remote_base)

        else:
            # Non-Docker Deployment (Static file / code upload)
            print_separator("─", 50, Fore.MAGENTA)
            log_step(name, "UPLOAD", "Uploading build artifacts to remote server...")
            upload_list = cfg.get("upload") or []
            if isinstance(upload_list, str):
                upload_list = [upload_list]

            if not upload_list:
                # Default: upload entire working dir or dist folder if present
                candidate_dist = os.path.join(work_dir, "dist")
                if os.path.isdir(candidate_dist):
                    upload_list.append(f"dist/ -> {remote_base}")
                else:
                    upload_list.append(f". -> {remote_base}")

            clean_remote = cfg.get("clean_remote") is True or cfg.get("empty_remote") is True

            for up in upload_list:
                src, dst = "", ""
                if isinstance(up, dict):
                    src, dst = up.get("src", ""), up.get("dest", "")
                elif isinstance(up, str):
                    parts = up.replace("->", " ").split()
                    if len(parts) >= 2:
                        src, dst = parts[0], parts[1]
                    else:
                        src, dst = parts[0], remote_base

                dst = dst.replace("${remote_dir}", remote_base).replace("$remote_dir", remote_base)
                if not dst.startswith("/"):
                    dst = f"{remote_base}/{dst}"
                dst = re.sub(r"/+", "/", dst).rstrip("/")

                local_full = os.path.normpath(os.path.join(work_dir, src) if not os.path.isabs(src) else src)

                # If clean_remote is enabled, empty destination directory on VPS before upload
                if clean_remote and proto == "ssh":
                    log_info(f"Emptying remote destination before upload: {dst}")
                    conn.run_cmd(f"rm -rf '{dst}'/* '{dst}'/.[!.]* 2>/dev/null || true")

                if os.path.isdir(local_full):
                    if use_archive and proto == "ssh":
                        conn.upload_archive(local_full, dst, ignore_patterns=ignore_list, retries=retries, overwrite=overwrite)
                    else:
                        conn.upload_directory(local_full, dst, ignore_patterns=ignore_list, max_workers=threads, retries=retries, overwrite=overwrite)
                elif os.path.isfile(local_full):
                    conn.upload_file(local_full, dst, retries=retries, overwrite=overwrite)
                else:
                    log_warning(f"File or directory to upload not found: {local_full}")

        # 5. Remote Post-Deploy / Run in VPS Phase
        if remote_steps:
            print_separator("─", 50, Fore.MAGENTA)
            log_step(name, "RUN IN VPS", f"Executing {len(remote_steps)} remote command(s)...")
            for s in remote_steps:
                action = s["action"]
                if action in ("RUN", "CMD"):
                    cmd = s["command"].replace("${remote_dir}", remote_base).replace("$remote_dir", remote_base)
                    conn.run_cmd(cmd, cwd=remote_base)
                elif action == "COPY":
                    local_src = os.path.normpath(os.path.join(project_root, s["src"]) if not os.path.isabs(s["src"]) else s["src"])
                    remote_dst = s["dest"].replace("${remote_dir}", remote_base).replace("$remote_dir", remote_base)
                    if not remote_dst.startswith("/"):
                        remote_dst = f"{remote_base}/{remote_dst}"
                    remote_dst = re.sub(r"/+", "/", remote_dst).rstrip("/")
                    if os.path.isdir(local_src):
                        if use_archive and proto == "ssh":
                            conn.upload_archive(local_src, remote_dst, ignore_patterns=ignore_list, retries=retries, overwrite=overwrite)
                        else:
                            conn.upload_directory(local_src, remote_dst, ignore_patterns=ignore_list, max_workers=threads, retries=retries, overwrite=overwrite)
                    elif os.path.isfile(local_src):
                        conn.upload_file(local_src, remote_dst, retries=retries, overwrite=overwrite)

        log_success(f"Service '{name}' deployed successfully!")

    finally:
        if conn:
            conn.close()


# =============================================================================
# 📖 CLI HELP & EXAMPLES
# =============================================================================

EXAMPLE_DEPLOY_YAML = """# =============================================================================
# 🚀 Universal Deployer Configuration (deploy.yml)
# =============================================================================
# Environment variables like ${VPS_IP} or ${SSH_KEY_PATH} are loaded from .env!

server:
  type: ssh                     # "ssh" (SFTP + Shell) or "ftp" (File transfer only)
  host: ${VPS_IP}               # VPS Hostname or IP
  user: ${VPS_USER:-root}       # User (defaults to root)
  port: 22                      # Port (22 for SSH, 21 for FTP)
  key_path: ${SSH_KEY_PATH}     # Path to SSH private key
  passphrase: ${SSH_PASSPHRASE} # (Optional) Passphrase for private key
  password: ${VPS_PASSWORD}     # (Optional) Password for SSH or FTP
  remote_dir: /opt/my-app       # Remote base directory on VPS
  threads: 8                    # (Optional) Concurrent upload threads (default: 8)
  retries: 5                    # (Optional) Auto-reconnect & retry attempts on network drop (default: 5)
  # archive: true               # (Optional) Ultra-fast 1-shot compressed archive sync (SSH only)
  # overwrite: false            # (Optional) Set false to skip files that already exist on server (default: true)

services:
  # ---------------------------------------------------------------------------
  # 🌐 Frontend (React / Next.js / Vue / HTML) - WITHOUT DOCKER
  # ---------------------------------------------------------------------------
  frontend:
    description: "Build frontend locally and sync static files to VPS"
    docker: false              # No docker for frontend
    work_dir: ./frontend       # Working directory

    # Dockerfile-like build instructions:
    build:
      - RUN npm install
      - RUN npm run build
      - COPY package.json dist/package.json

    # Upload dist output to remote directory
    upload:
      - dist/ -> ${remote_dir}/frontend/dist

    # (Optional) Upload behavior settings:
    # overwrite: false         # (Optional) Set false to skip files that already exist on server (default: true)
    # clean_remote: true       # Set true to wipe destination directory before upload
    # archive: false           # Set true for ultra-fast single-shot archive transfer (SSH only)
    # threads: 8               # Number of concurrent upload threads (default: 8)
    # retries: 5               # Retry attempts on network drop (default: 5)

    # Commands executed on remote VPS (SSH only):
    run_in_vps:
      - RUN systemctl reload nginx
      - RUN echo "Frontend updated!"

  # ---------------------------------------------------------------------------
  # 🐳 Backend (FastAPI / Node / Python) - WITH DOCKER
  # ---------------------------------------------------------------------------
  backend:
    description: "Build local Docker image, transfer tar, and restart container"
    work_dir: ./backend

    docker:
      enabled: true
      compose_file: docker-compose.yml
      # env_file: .env.production # (Optional: auto-detected from docker-compose.yml!)
      service_name: backend
      build_mode: local        # "local" (tarball upload) or "remote" (build on VPS)
      image: my-backend:latest
      context: ./backend

    # Run on VPS before docker starts:
    before_deploy:
      - RUN mkdir -p ${remote_dir}/backend/data

    # Run on VPS after deployment:
    # (Note: 'docker compose up -d <service>' is already executed automatically!)
    run_in_vps:
      - RUN docker compose ps
      - RUN docker compose logs --tail=25 backend

  # ---------------------------------------------------------------------------
  # 📁 API / Worker (Direct Working Directory Upload with Ignore Rules)
  # ---------------------------------------------------------------------------
  api:
    description: "Sync current working directory directly to VPS with ignore rules"
    docker: false
    work_dir: ./api

    # Upload entire working directory (.) to remote VPS destination
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

    # Upload settings:
    # overwrite: false         # (Optional) Set false to skip files that already exist on server (default: true)
    # clean_remote: true       # (Optional) Wipe destination directory before uploading
    # archive: false           # (Optional) Fast 1-shot archive sync for large folders
    # threads: 8               # Number of concurrent upload threads
    # retries: 5               # Retry attempts on network drop

    run_in_vps:
      - RUN pm2 restart api || pm2 start index.js --name api
"""

def print_help_screen():
    banner()
    help_text = f"""{Fore.WHITE}{Style.BRIGHT}USAGE:{Style.RESET_ALL}
  uhdeploy [OPTIONS] [SERVICE_NAME]
  {Fore.LIGHTBLACK_EX}(or python -m uhdeploy [OPTIONS] [SERVICE_NAME]){Style.RESET_ALL}

{Fore.WHITE}{Style.BRIGHT}DESCRIPTION:{Style.RESET_ALL}
  uhdeploy reads your {Fore.CYAN}deploy.yml{Style.RESET_ALL} (or {Fore.CYAN}deploy.yaml{Style.RESET_ALL}) file and deploys
  your services to a VPS using SSH/SFTP or FTP. It supports Docker packaging,
  local build pipelines, and Dockerfile-style step syntax ({Fore.YELLOW}RUN{Style.RESET_ALL}, {Fore.YELLOW}COPY{Style.RESET_ALL}, {Fore.YELLOW}CMD{Style.RESET_ALL}).

{Fore.WHITE}{Style.BRIGHT}OPTIONS:{Style.RESET_ALL}
  {Fore.GREEN}-h, --help{Style.RESET_ALL}               Show this colorful help message and exit.
  {Fore.GREEN}-e, --example{Style.RESET_ALL}            Display a syntax-highlighted example deploy.yml.
  {Fore.GREEN}--init{Style.RESET_ALL}                   Generate a starter {Fore.CYAN}deploy.yml{Style.RESET_ALL} in the current directory.
  {Fore.GREEN}-f, --file PATH{Style.RESET_ALL}          Specify path to deploy configuration file.
  {Fore.GREEN}-p, --project DIR{Style.RESET_ALL}        Specify project directory containing deploy configuration.
  {Fore.GREEN}-s, --service NAME{Style.RESET_ALL}       Name of service to deploy (or {Fore.CYAN}'all'{Style.RESET_ALL} for all services).
  {Fore.GREEN}-l, --list{Style.RESET_ALL}               List all services available in the configuration file.
  {Fore.GREEN}-t, --threads N{Style.RESET_ALL}          Number of concurrent upload threads (default: 8).
  {Fore.GREEN}--retries N{Style.RESET_ALL}               Max retry & reconnect attempts on network drops (default: 5).
  {Fore.GREEN}--archive{Style.RESET_ALL}                 Package files into compressed archive for fast sync (SSH only).
  {Fore.GREEN}--overwrite{Style.RESET_ALL}               Force overwrite existing files on destination server (default: enabled).
  {Fore.GREEN}--no-overwrite{Style.RESET_ALL}            Do not overwrite files that already exist on server (skip existing).
  {Fore.GREEN}--dry-run{Style.RESET_ALL}                Validate configuration and simulate steps without connecting.

{Fore.WHITE}{Style.BRIGHT}INTERACTIVE DISCOVERY:{Style.RESET_ALL}
  If no config file is found in the current folder, uhdeploy prompts you
  to enter your project path or config file path automatically.

{Fore.WHITE}{Style.BRIGHT}DOCKERFILE-STYLE STEP COMMANDS:{Style.RESET_ALL}
  In {Fore.CYAN}build{Style.RESET_ALL}, {Fore.CYAN}before_deploy{Style.RESET_ALL}, or {Fore.CYAN}run_in_vps{Style.RESET_ALL}, you can write steps like:
  • {Fore.YELLOW}RUN <shell command>{Style.RESET_ALL}        Executes command (locally or on VPS)
  • {Fore.YELLOW}COPY <src> <dest>{Style.RESET_ALL}          Copies local file/folder or uploads to VPS
  • {Fore.YELLOW}WORKDIR <dir>{Style.RESET_ALL}              Changes working directory
  • {Fore.YELLOW}CMD <command>{Style.RESET_ALL}              Alias for RUN

{Fore.WHITE}{Style.BRIGHT}SSH VS. FTP CAPABILITIES:{Style.RESET_ALL}
  • {Fore.CYAN}SSH{Style.RESET_ALL}: Full support for file transfers (SFTP), remote terminal commands,
         Docker container management, and system services.
  • {Fore.CYAN}FTP{Style.RESET_ALL}: File transfer protocol only. Useful for static / PHP hosting.
         Remote shell commands ({Fore.YELLOW}run_in_vps{Style.RESET_ALL}) are not supported over FTP.

{Fore.WHITE}{Style.BRIGHT}EXAMPLES OF RUNNING:{Style.RESET_ALL}
  {Fore.LIGHTBLACK_EX}# Interactive service selection menu:{Style.RESET_ALL}
  uhdeploy

  {Fore.LIGHTBLACK_EX}# Deploy frontend only:{Style.RESET_ALL}
  uhdeploy frontend

  {Fore.LIGHTBLACK_EX}# Deploy all services:{Style.RESET_ALL}
  uhdeploy all

  {Fore.LIGHTBLACK_EX}# Dry-run backend to verify steps:{Style.RESET_ALL}
  uhdeploy backend --dry-run
"""
    print(help_text)

def print_example_file():
    banner()
    print(f"{Fore.CYAN}📄 EXAMPLE DEPLOYMENT FILE (deploy.yml):{Style.RESET_ALL}\n")
    for line in EXAMPLE_DEPLOY_YAML.splitlines():
        if line.strip().startswith("#"):
            print(f"{Fore.LIGHTBLACK_EX}{line}{Style.RESET_ALL}")
        elif line.strip().endswith(":") and not line.strip().startswith("-"):
            print(f"{Fore.CYAN}{Style.BRIGHT}{line}{Style.RESET_ALL}")
        elif line.strip().startswith("- RUN") or line.strip().startswith("- CMD"):
            print(f"{Fore.YELLOW}{line}{Style.RESET_ALL}")
        elif line.strip().startswith("- COPY"):
            print(f"{Fore.LIGHTBLUE_EX}{line}{Style.RESET_ALL}")
        elif "${" in line:
            print(f"{Fore.GREEN}{line}{Style.RESET_ALL}")
        else:
            print(f"{Fore.WHITE}{line}{Style.RESET_ALL}")
    print()

def init_deploy_file():
    target = os.path.join(os.getcwd(), "deploy.yml")
    if os.path.exists(target):
        log_warning(f"'deploy.yml' already exists in {os.getcwd()}.")
        confirm = input(f"{Fore.CYAN}Overwrite? (y/N): {Style.RESET_ALL}").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return
    with open(target, "w", encoding="utf-8") as f:
        f.write(EXAMPLE_DEPLOY_YAML)
    log_success(f"Generated starter 'deploy.yml' in: {target}")


# =============================================================================
# 📋 INTERACTIVE SERVICE SELECTION MENU
# =============================================================================

def select_service_interactive(services):
    banner()
    svc_keys = list(services.keys())
    if not svc_keys:
        log_error("No services available to deploy.")
        sys.exit(1)

    print(f"{Fore.WHITE}{Style.BRIGHT}Select component to deploy:{Style.RESET_ALL}\n")
    for idx, name in enumerate(svc_keys, 1):
        s_cfg = services[name]
        is_docker = False
        docker_val = s_cfg.get("docker")
        if isinstance(docker_val, dict):
            is_docker = docker_val.get("enabled", True)
        elif isinstance(docker_val, bool):
            is_docker = docker_val

        docker_badge = f"{Fore.CYAN}[Docker]{Style.RESET_ALL}" if is_docker else f"{Fore.LIGHTBLUE_EX}[No Docker]{Style.RESET_ALL}"
        proto = (s_cfg.get("server", {}).get("type") or "ssh").upper()
        proto_badge = f"{Fore.YELLOW}[{proto}]{Style.RESET_ALL}"
        desc = s_cfg.get("description", "")
        desc_str = f" - {Fore.LIGHTBLACK_EX}{desc}{Style.RESET_ALL}" if desc else ""

        print(f"  {Fore.GREEN}{Style.BRIGHT}{idx}){Style.RESET_ALL} {Fore.WHITE}{Style.BRIGHT}{name:<15}{Style.RESET_ALL} {docker_badge} {proto_badge}{desc_str}")

    all_idx = len(svc_keys) + 1
    print(f"  {Fore.GREEN}{Style.BRIGHT}{all_idx}){Style.RESET_ALL} {Fore.WHITE}{Style.BRIGHT}All Components  {Style.RESET_ALL} {Fore.LIGHTBLACK_EX}(Deploy all services sequentially){Style.RESET_ALL}")
    print(f"  {Fore.RED}q){Style.RESET_ALL} Quit\n")

    while True:
        try:
            choice = input(f"{Fore.CYAN}Enter choice (1-{all_idx} or q): {Style.RESET_ALL}").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            sys.exit(0)

        if choice == "q":
            print(f"{Fore.YELLOW}Goodbye!{Style.RESET_ALL}")
            sys.exit(0)

        if choice.isdigit():
            c_int = int(choice)
            if 1 <= c_int <= len(svc_keys):
                return [svc_keys[c_int - 1]]
            elif c_int == all_idx:
                return svc_keys

        log_error("Invalid selection. Please choose an option from the menu.")


# =============================================================================
# 🏁 MAIN ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        prog="uhdeploy",
        description="uhdeploy - Universal Local-to-VPS Deployment CLI",
        add_help=False
    )
    parser.add_argument("service", nargs="?", default=None, help="Service name to deploy (or 'all')")
    parser.add_argument("-h", "--help", action="store_true", help="Show help screen")
    parser.add_argument("-e", "--example", action="store_true", help="Show example deploy.yml configuration")
    parser.add_argument("--init", action="store_true", help="Generate starter deploy.yml in current directory")
    parser.add_argument("-f", "--file", dest="config_file", default=None, help="Path to deploy configuration file")
    parser.add_argument("-p", "--project", dest="project_dir", default=None, help="Project directory path")
    parser.add_argument("-s", "--service", dest="flag_service", default=None, help="Service name to deploy")
    parser.add_argument("-l", "--list", action="store_true", help="List all configured services")
    parser.add_argument("-t", "--threads", type=int, default=None, help="Number of concurrent upload threads (default: 8)")
    parser.add_argument("--retries", type=int, default=None, help="Max retry/reconnect attempts on network drops (default: 5)")
    parser.add_argument("--archive", action="store_true", default=None, help="Package files into compressed archive for fast sync (SSH only)")
    parser.add_argument("--overwrite", action="store_true", default=None, help="Force overwrite files on remote server (default behavior)")
    parser.add_argument("--no-overwrite", action="store_true", default=False, help="Do not overwrite files that already exist on the server (skip existing files)")
    parser.add_argument("--dry-run", action="store_true", help="Dry run deployment without making remote changes")

    args = parser.parse_args()

    # Help flag
    if args.help:
        print_help_screen()
        sys.exit(0)

    # Example flag
    if args.example:
        print_example_file()
        sys.exit(0)

    # Init flag
    if args.init:
        banner()
        init_deploy_file()
        sys.exit(0)

    # Find configuration file (Interactive flow if not found)
    config_path, project_root = find_config_interactive(
        cli_file=args.config_file,
        cli_project=args.project_dir
    )

    log_info(f"Loaded configuration: {Fore.WHITE}{config_path}")
    log_info(f"Project Root: {Fore.WHITE}{project_root}")

    # Parse config and substitute environment variables
    services, env_vars = parse_deploy_config(config_path, project_root)

    # List services flag
    if args.list:
        banner()
        print(f"{Fore.WHITE}{Style.BRIGHT}Configured Services in {os.path.basename(config_path)}:{Style.RESET_ALL}\n")
        for s_name, s_data in services.items():
            s_type = "Docker" if s_data.get("docker") else "No Docker"
            proto = (s_data.get("server", {}).get("type") or "ssh").upper()
            print(f"  • {Fore.GREEN}{s_name:<16}{Style.RESET_ALL} [{s_type}] [{proto}] - {s_data.get('description', '')}")
        print()
        sys.exit(0)

    # Determine service to deploy
    target_service = args.flag_service or args.service

    if target_service:
        if target_service.lower() == "all":
            selected_services = list(services.keys())
        else:
            if target_service not in services:
                log_error(f"Service '{target_service}' is not defined in {os.path.basename(config_path)}.")
                log_info(f"Available services: {', '.join(services.keys())}")
                sys.exit(1)
            selected_services = [target_service]
    else:
        # If only 1 service defined, use it directly or show interactive menu
        selected_services = select_service_interactive(services)

    # Execute deployment for chosen services
    banner()
    log_info(f"Deploying service(s): {Fore.WHITE}{', '.join(selected_services)}")
    if args.dry_run:
        log_warning("DRY-RUN MODE ENABLED: No remote changes or uploads will be performed.")

    cli_overwrite = None
    if args.no_overwrite:
        cli_overwrite = False
    elif args.overwrite:
        cli_overwrite = True

    for s_name in selected_services:
        deploy_service(
            name=s_name,
            cfg=services[s_name],
            project_root=project_root,
            dry_run=args.dry_run,
            cli_threads=args.threads,
            cli_retries=args.retries,
            cli_archive=args.archive,
            cli_overwrite=cli_overwrite
        )

    print_separator("═", 75, Fore.GREEN)
    log_success("All selected deployment tasks completed successfully!")
    print_separator("═", 75, Fore.GREEN)

if __name__ == "__main__":
    main()

