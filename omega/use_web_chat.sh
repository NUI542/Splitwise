#!/usr/bin/env bash
# Move Omega onto its web chat channel, connected to the Edition Deal Agent's
# "Ask the agent" panel, with the edition_deals plugin mounted from this repo.
#
#   bash omega/use_web_chat.sh [container-name]        (default: omega)
#
# Run it where `docker` works (on this machine: Ubuntu under WSL). It:
#   1. reads EDA_OMEGA_WS_TOKEN from .env, creating one if it's missing;
#   2. copies the existing container's image, Omega options, volumes and
#      environment (your API keys go to a private temp file, are never
#      printed, and are deleted afterwards);
#   3. writes var/omega/plugins.yaml: Omega's own list plus edition_deals;
#   4. stops the existing container and keeps it as <name>-telegram-backup;
#   5. starts a new <name> with commchannel=websocket, WS_URL and WS_TOKEN.
#
# Undo:  docker rm -f omega && docker rename omega-telegram-backup omega && docker start omega
set -euo pipefail

NAME="${1:-omega}"
BACKUP="${NAME}-telegram-backup"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OMEGA=/PeTTa/repos/Omega
WS_URL="${EDA_WS_URL:-ws://host.docker.internal:8000/omega/ws}"

docker inspect "$NAME" >/dev/null 2>&1 || { echo "No container named $NAME." >&2; exit 1; }
if docker inspect "$BACKUP" >/dev/null 2>&1; then
  echo "$BACKUP already exists. Remove or rename it first, so the backup isn't lost." >&2
  exit 1
fi

# 1. The token Omega presents to the deal agent.
ENV_FILE="$REPO/.env"
TOKEN="$(grep -E '^EDA_OMEGA_WS_TOKEN=' "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- || true)"
if [ -z "$TOKEN" ]; then
  TOKEN="$(head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 40)"
  printf '\n# The token Omega uses to connect to the deal agent (/omega/ws).\nEDA_OMEGA_WS_TOKEN=%s\n' "$TOKEN" >> "$ENV_FILE"
  echo "Created EDA_OMEGA_WS_TOKEN in .env. Restart the deal agent's API so it picks it up."
fi

# 2. The existing container's settings.
IMAGE="$(docker inspect -f '{{.Config.Image}}' "$NAME")"
mapfile -t ARGS < <(docker inspect -f '{{range .Config.Cmd}}{{println .}}{{end}}' "$NAME" \
  | sed '/^$/d' | grep -vE '^(commchannel|WS_URL|WS_TOKEN|TG_POLL_TIMEOUT)=' || true)

TMP="$(mktemp -d)"
chmod 700 "$TMP"
trap 'rm -rf "$TMP"' EXIT
docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$NAME" | sed '/^$/d' > "$TMP/env"
chmod 600 "$TMP/env"

mapfile -t MOUNTS < <(docker inspect -f \
  '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}}{{else}}{{.Source}}{{end}}:{{.Destination}}{{println}}{{end}}' "$NAME" \
  | sed '/^$/d' | grep -vE ":$OMEGA/(plugins/edition_deals|config/plugins.yaml)$" || true)
VOLUMES=()
for m in "${MOUNTS[@]}"; do VOLUMES+=(-v "$m"); done

# How it was run: terminal (-it, which Omega's built-in proxy needs), --init,
# security options and log driver.
RUNOPTS=()
[ "$(docker inspect -f '{{.Config.Tty}}' "$NAME")" = "true" ] && RUNOPTS+=(-t)
[ "$(docker inspect -f '{{.Config.OpenStdin}}' "$NAME")" = "true" ] && RUNOPTS+=(-i)
[ "$(docker inspect -f '{{if .HostConfig.Init}}{{.HostConfig.Init}}{{end}}' "$NAME")" = "true" ] && RUNOPTS+=(--init)
while read -r opt; do [ -n "$opt" ] && RUNOPTS+=(--security-opt "$opt"); done \
  < <(docker inspect -f '{{range .HostConfig.SecurityOpt}}{{println .}}{{end}}' "$NAME")
LOGDRIVER="$(docker inspect -f '{{.HostConfig.LogConfig.Type}}' "$NAME")"
[ -n "$LOGDRIVER" ] && RUNOPTS+=(--log-driver "$LOGDRIVER")

# 3. Omega's plugin list, plus ours.
mkdir -p "$REPO/var/omega"
docker cp "$NAME:$OMEGA/config/plugins.yaml" "$TMP/plugins.yaml"
grep -q "name: edition_deals" "$TMP/plugins.yaml" || \
  printf '\n- name: edition_deals\n  loader: metta\n  location: "{REPO}/plugins/edition_deals"\n' >> "$TMP/plugins.yaml"
cp "$TMP/plugins.yaml" "$REPO/var/omega/plugins.yaml"
chmod 644 "$REPO/var/omega/plugins.yaml" || true

# 4. Keep the old container.
echo "Stopping $NAME and keeping it as $BACKUP"
docker stop "$NAME" >/dev/null 2>&1 || true
docker rename "$NAME" "$BACKUP"

# 5. The new one, on the web chat channel.
echo "Starting $NAME on the web chat channel ($WS_URL)"
docker run -d "${RUNOPTS[@]}" --name "$NAME" --env-file "$TMP/env" \
  --add-host host.docker.internal:host-gateway \
  "${VOLUMES[@]}" \
  -v "$REPO/omega/edition_deals:$OMEGA/plugins/edition_deals:ro" \
  -v "$REPO/var/omega/plugins.yaml:$OMEGA/config/plugins.yaml:ro" \
  "$IMAGE" "${ARGS[@]}" commchannel=websocket "WS_URL=$WS_URL" "WS_TOKEN=$TOKEN" >/dev/null

echo
echo "Done. Omega connects to the deal agent by itself; check with:"
echo "  docker logs -f $NAME 2>&1 | grep -E 'edition|plugin|websocket|Connected'"
echo "or open the app's \"Ask the agent\" panel, which shows whether Omega is connected."
