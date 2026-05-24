#!/usr/bin/env bash
#
# Создаёт ServiceAccount в minikube с правами на discovery pod'ов и нод
# и кладёт его bearer-токен и CA-сертификат рядом, чтобы Prometheus в
# Docker мог обращаться к Kubernetes API (см. ../prometheus.yml).
#
# Использование:
#   ./gen-token.sh                       # SA "prometheus" в ns "monitoring"
#   NAMESPACE=default ./gen-token.sh
#   SA_NAME=prom TTL=720h ./gen-token.sh
#   CONTEXT=minikube ./gen-token.sh
#
# После запуска перечитай конфиг Prometheus:
#   docker compose restart prometheus

set -euo pipefail

NAMESPACE="${NAMESPACE:-monitoring}"
SA_NAME="${SA_NAME:-prometheus}"
TTL="${TTL:-24h}"
CONTEXT="${CONTEXT:-$(kubectl config current-context)}"
OUT_DIR="$(cd "$(dirname "$0")" && pwd)"

KCTL=(kubectl --context "$CONTEXT")

echo "Контекст:  $CONTEXT"
echo "Namespace: $NAMESPACE"
echo "SA:        $SA_NAME"
echo "TTL:       $TTL"
echo

# 1. namespace
"${KCTL[@]}" get ns "$NAMESPACE" >/dev/null 2>&1 \
  || "${KCTL[@]}" create ns "$NAMESPACE"

# 2. ServiceAccount
"${KCTL[@]}" -n "$NAMESPACE" get sa "$SA_NAME" >/dev/null 2>&1 \
  || "${KCTL[@]}" -n "$NAMESPACE" create sa "$SA_NAME"

# 3. ClusterRole + ClusterRoleBinding с правами для kubernetes_sd_configs
#    (pod role и node role) и для kubelet /metrics/resource через node proxy.
"${KCTL[@]}" apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ${SA_NAME}-discovery
rules:
  - apiGroups: [""]
    resources: ["nodes", "nodes/proxy", "nodes/metrics", "services", "endpoints", "pods"]
    verbs: ["get", "list", "watch"]
  - nonResourceURLs: ["/metrics"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: ${SA_NAME}-discovery
subjects:
  - kind: ServiceAccount
    name: ${SA_NAME}
    namespace: ${NAMESPACE}
roleRef:
  kind: ClusterRole
  name: ${SA_NAME}-discovery
  apiGroup: rbac.authorization.k8s.io
EOF

# 4. Bearer token (k8s 1.24+)
TOKEN="$("${KCTL[@]}" -n "$NAMESPACE" create token "$SA_NAME" --duration="$TTL")"
printf '%s' "$TOKEN" > "$OUT_DIR/token"
chmod 600 "$OUT_DIR/token"

# 5. Быстрая sanity-проверка: дёрнем API от имени нового SA.
APISERVER="$("${KCTL[@]}" config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
if curl -sk -o /dev/null -w '%{http_code}' \
     -H "Authorization: Bearer $TOKEN" \
     "$APISERVER/api/v1/nodes" | grep -q '^200$'; then
  echo "API server $APISERVER ответил 200 OK."
else
  echo "ВНИМАНИЕ: проверка через $APISERVER не вернула 200." >&2
fi

echo
echo "Готово:"
echo "  $OUT_DIR/token   (TTL: $TTL)"
echo
echo "Перезапусти Prometheus, чтобы он перечитал файлы:"
echo "  docker compose restart prometheus"
