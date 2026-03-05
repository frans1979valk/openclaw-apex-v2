FROM node:20-alpine
WORKDIR /workspace
RUN npm i -g openclaw@latest || true
CMD ["sh", "-lc", "echo 'OpenClaw ready. Use: docker compose exec openclaw openclaw --help' && tail -f /dev/null"]
