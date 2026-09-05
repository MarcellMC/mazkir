# infra/coding-agent/Dockerfile
#
# Unified devcontainer image: used both by CodingTasksService.spawn_container
# (automated, headless) and by interactive Remote Control sessions where a
# human connects with their own dotfiles (LazyVim, tmux, zsh, lazygit) — so
# a Mazkir-spawned task can be debugged/taken over with normal tools instead
# of a bare shell if something goes wrong.
FROM node:22-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    curl \
    wget \
    tmux \
    zsh \
    stow \
    ripgrep \
    fd-find \
    build-essential \
    unzip \
    ruby \
    ruby-dev \
    python3 \
    python3-venv \
    python3-dev \
    && mkdir -p -m 755 /etc/apt/keyrings \
    && wget -nv -O /etc/apt/keyrings/githubcli-archive-keyring.gpg https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/fdfind /usr/local/bin/fd

# Neovim: LazyVim needs a recent build, older than apt ships on Debian slim.
# The AppImage the dotfiles repo carries needs FUSE, which containers
# generally don't have — use the official prebuilt release tarball instead.
RUN curl -fsSL https://github.com/neovim/neovim/releases/latest/download/nvim-linux-x86_64.tar.gz -o /tmp/nvim.tar.gz \
    && tar -C /opt -xzf /tmp/nvim.tar.gz \
    && mv /opt/nvim-linux-x86_64 /opt/nvim \
    && ln -s /opt/nvim/bin/nvim /usr/local/bin/nvim \
    && rm /tmp/nvim.tar.gz

# lazygit: no apt package, fetch the release binary directly.
RUN LAZYGIT_VERSION=$(curl -fsSL "https://api.github.com/repos/jesseduffield/lazygit/releases/latest" | grep -Po '"tag_name":\s*"v\K[^"]*') \
    && curl -fsSL -o /tmp/lazygit.tar.gz "https://github.com/jesseduffield/lazygit/releases/download/v${LAZYGIT_VERSION}/lazygit_${LAZYGIT_VERSION}_Linux_x86_64.tar.gz" \
    && tar -C /tmp -xzf /tmp/lazygit.tar.gz lazygit \
    && install /tmp/lazygit /usr/local/bin/lazygit \
    && rm /tmp/lazygit.tar.gz /tmp/lazygit

RUN gem install tmuxinator

RUN npm install -g @anthropic-ai/claude-code

# uv: the project's Python apps are installed with it, and a session that
# has to bootstrap its own interpreter wastes minutes and leaves a broken
# venv behind (observed: a real session shipped an activate-scripts-only
# venv with no interpreter). Installed to /usr/local/bin so it is on PATH
# for every user.
RUN curl -fsSL https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

# Doppler: sessions fetch configuration at runtime rather than carrying a
# .env of secrets in the clone. The token arrives via the credential
# env-file at launch, never in argv.
RUN curl -fsSL https://cli.doppler.com/install.sh | sh

# Pre-install the vault-server dependency set. Without this, a session's
# first `pytest` triggers a multi-minute install -- and one real session
# backgrounded that install, ended its turn waiting for it, and exited
# mid-task with everything uncommitted. Removing the wait removes the
# temptation to background it.
#
# Copied from apps/vault-server/pyproject.toml. The list is duplicated
# rather than COPYed so the build context stays this directory; a session
# whose branch adds a dependency installs only the delta, which is fast.
RUN uv pip install --system --break-system-packages \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.30.0" \
    "python-frontmatter>=1.0.0" \
    "python-dateutil>=2.8.2" \
    "pytz>=2024.1" \
    "anthropic>=0.18.0" \
    "google-api-python-client>=2.100.0" \
    "google-auth-httplib2>=0.1.0" \
    "google-auth-oauthlib>=1.0.0" \
    "httpx>=0.27.0" \
    "jsonschema>=4.20.0" \
    "pydantic>=2.5.0" \
    "pydantic-settings>=2.1.0" \
    "python-dotenv>=1.0.0" \
    "replicate>=0.25.0" \
    "Pillow>=10.0.0" \
    "python-multipart>=0.0.22" \
    "rapidfuzz>=3.6.0" \
    "python-json-logger>=2.0.7" \
    "opentelemetry-sdk>=1.27.0" \
    "opentelemetry-exporter-otlp-proto-http>=1.27.0" \
    "opentelemetry-instrumentation-fastapi>=0.48b0" \
    "openinference-instrumentation-anthropic>=0.1.14" \
    "pytest>=8.0.0" \
    "pytest-asyncio>=0.23.0"

# Use the base image's existing non-root `node` user (UID 1000) rather than
# creating a new one — a fresh useradd would land on the next free UID
# (1001), which does not match a typical single-user host's UID (1000),
# breaking write access to bind-mounted worktrees owned by the host user.
#
# Home directory moved to /home/marcellmc (matching the actual host user),
# not left at the default /home/node. Confirmed necessary, not cosmetic:
# Claude Code's own plugin state (installed_plugins.json,
# known_marketplaces.json) stores absolute host paths like
# "/home/marcellmc/.claude/plugins/marketplaces/...". Since these files are
# bind-mounted (not copied) from the host, mounting them at any other path
# (e.g. the default /home/node/.claude/plugins) leaves every recorded
# location pointing at a path that doesn't exist in the container --
# confirmed as the actual cause of "cache-miss" marketplace-load errors and
# every plugin showing disabled. Rewriting the JSON to match a different
# container path was considered and rejected: since the files are shared
# with the host (not copied), any such rewrite would corrupt the host's
# real config for its own interactive Claude Code sessions.
RUN usermod -d /home/marcellmc -m -s /usr/bin/zsh node \
    && mkdir -p /home/marcellmc/.claude /workspace \
    && touch /home/marcellmc/.claude.json \
    && chown node:node /home/marcellmc/.claude /home/marcellmc/.claude.json /workspace

# Stand-in for xdg-open. Claude Code shells out to xdg-open to open the
# OAuth login URL, and Debian slim ships no xdg-utils, no browser, no
# DISPLAY and no clipboard binary -- so the URL could only be printed,
# wrapped across a terminal line, and hand-transcribed. The shim captures
# it to the /workspace bind mount and pushes it to the host clipboard over
# OSC 52 instead. BROWSER is set as well because that is the other name
# the same lookup goes by.
COPY open-url.sh /usr/local/bin/xdg-open
RUN chmod +x /usr/local/bin/xdg-open
ENV BROWSER=/usr/local/bin/xdg-open

COPY --chown=node:node entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER node
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
