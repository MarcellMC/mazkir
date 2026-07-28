# infra/coding-agent/Dockerfile
FROM node:22-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

# Use the base image's existing non-root `node` user (UID 1000) rather than
# creating a new one — a fresh useradd would land on the next free UID
# (1001), which does not match a typical single-user host's UID (1000),
# breaking write access to bind-mounted worktrees owned by the host user.
RUN mkdir -p /home/node/.claude /workspace \
    && touch /home/node/.claude.json \
    && chown node:node /home/node/.claude /home/node/.claude.json /workspace

USER node
WORKDIR /workspace
