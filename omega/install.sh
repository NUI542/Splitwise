#!/usr/bin/env bash
# Install the Edition Deal Agent plugin into an existing Omega container.
#
#   bash omega/install.sh [container-name]      (default: omega)
#
# Copies omega/edition_deals/ to /PeTTa/repos/Omega/plugins/edition_deals/
# and adds the plugin to config/plugins.yaml (once). Safe to run again after
# changing the plugin. Run it where `docker` works (on this machine: Ubuntu
# under WSL). The container can be stopped or running; restart it afterwards.
#
# Changes live in the container itself: recreating the container (for
# example with Omega's setup script) removes them. See omega/README.md for
# the bind-mount alternative that survives that.
set -euo pipefail

CONTAINER="${1:-omega}"
HERE="$(cd "$(dirname "$0")" && pwd)"
OMEGA=/PeTTa/repos/Omega
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

docker inspect "$CONTAINER" >/dev/null 2>&1 || { echo "No container named $CONTAINER" >&2; exit 1; }

echo "Copying the plugin into $CONTAINER:$OMEGA/plugins/edition_deals"
mkdir -p "$TMP/edition_deals"
cp "$HERE/edition_deals/edition_deals.metta" "$HERE/edition_deals/edition_deal_skills.py" "$TMP/edition_deals/"
chmod 0755 "$TMP/edition_deals"
chmod 0644 "$TMP/edition_deals/"*
docker cp "$TMP/edition_deals" "$CONTAINER:$OMEGA/plugins/"

docker cp "$CONTAINER:$OMEGA/config/plugins.yaml" "$TMP/plugins.yaml"
if grep -q "name: edition_deals" "$TMP/plugins.yaml"; then
  echo "config/plugins.yaml already lists edition_deals"
else
  echo "Adding edition_deals to config/plugins.yaml"
  printf '\n- name: edition_deals\n  loader: metta\n  location: "{REPO}/plugins/edition_deals"\n' >> "$TMP/plugins.yaml"
  chmod 0644 "$TMP/plugins.yaml"
  docker cp "$TMP/plugins.yaml" "$CONTAINER:$OMEGA/config/plugins.yaml"
fi

echo
echo "Done. Next:"
echo "  docker restart $CONTAINER     # or: docker start $CONTAINER"
echo "  docker logs -f $CONTAINER | grep -E 'edition|plugin'"
echo "You should see: Plugin edition_deals is loaded"
