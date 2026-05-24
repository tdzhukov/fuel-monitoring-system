#!/usr/bin/env bash
#
# Генерирует kubeconfig, который можно смонтировать в Docker-контейнер
# load-analytics-service, чтобы тот ходил в локальный minikube.
#
# Использование:
#   ./gen-kubeconfig.sh                    # запишет в ./kubeconfig-docker.yaml
#   ./gen-kubeconfig.sh /tmp/kube.yaml     # в указанный путь

set -euo pipefail

OUT="${1:-$(dirname "$0")/kubeconfig-docker.yaml}"
CONTEXT="${CONTEXT:-$(kubectl config current-context)}"

if ! kubectl config get-contexts -o name | grep -qx "$CONTEXT"; then
  echo "error: контекст '$CONTEXT' не найден в ~/.kube/config" >&2
  exit 1
fi

kubectl config view --flatten --minify --context="$CONTEXT" \
  | sed -E 's#server: https?://(127\.0\.0\.1|localhost|0\.0\.0\.0):#server: https://host.docker.internal:#' \
  > "$OUT"

chmod 600 "$OUT"

echo "Сгенерирован $OUT (контекст: $CONTEXT)"
echo "Адрес API-сервера:"
grep '^\s*server:' "$OUT" | sed 's/^/  /'
