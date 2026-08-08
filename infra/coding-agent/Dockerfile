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

COPY --chown=node:node entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER node
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
