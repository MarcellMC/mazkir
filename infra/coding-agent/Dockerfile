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

# Use the base image's existing non-root `node` user (UID 1000) rather than
# creating a new one — a fresh useradd would land on the next free UID
# (1001), which does not match a typical single-user host's UID (1000),
# breaking write access to bind-mounted worktrees owned by the host user.
RUN usermod -s /usr/bin/zsh node \
    && mkdir -p /home/node/.claude /workspace \
    && touch /home/node/.claude.json \
    && chown node:node /home/node/.claude /home/node/.claude.json /workspace

COPY --chown=node:node entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER node
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
