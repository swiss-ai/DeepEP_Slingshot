#!/usr/bin/env bash
# wrap.sh server PORT DEV [opts...]   |   wrap.sh client PORT SERVER DEV [opts...]
# Runs /usr/bin/cxi_write_bw on the bare node. Clients retry while the server is still starting.
role=$1; port=$2; shift 2
if [ "$role" = server ]; then dev=$1; shift; else srv=$1; dev=$2; shift 2; fi
svc=""
if [ "${USE_SVC:-1}" = 1 ] && [ -n "${SLINGSHOT_DEVICES:-}" ]; then
  IFS=, read -ra devs <<< "$SLINGSHOT_DEVICES"; IFS=, read -ra svcs <<< "${SLINGSHOT_SVC_IDS:-}"
  for i in "${!devs[@]}"; do [ "${devs[$i]}" = "$dev" ] && svc="${svcs[$i]:-}"; done
fi
echo "# host=$(hostname) role=$role dev=$dev svc=${svc:-default} LD_LIBRARY_PATH=${LD_LIBRARY_PATH:-} opts=$*"
if [ "$role" = server ]; then cmd=(cxi_write_bw -d "$dev" -p "$port" ${svc:+-v $svc} "$@"); else cmd=(cxi_write_bw "$srv" -d "$dev" -p "$port" ${svc:+-v $svc} "$@"); fi
echo "# cmd: ${cmd[*]}"
attempt=0
while :; do
  attempt=$((attempt+1)); tmp=$(mktemp)
  timeout 150 "${cmd[@]}" > "$tmp" 2>&1; rc=$?
  if [ "$role" = client ] && [ $rc -ne 0 ] && grep -q "Connection refused" "$tmp" && [ $attempt -lt 20 ]; then rm -f "$tmp"; sleep 2; continue; fi
  cat "$tmp"; rm -f "$tmp"; echo "# attempts=$attempt rc=$rc"; exit $rc
done
