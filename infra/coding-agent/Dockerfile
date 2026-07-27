# infra/coding-agent/Dockerfile
FROM node:22-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

RUN useradd -m -s /bin/bash agent \
    && mkdir -p /home/agent/.claude \
    && chown agent:agent /home/agent/.claude

USER agent
WORKDIR /workspace
