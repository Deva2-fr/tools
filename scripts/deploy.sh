#!/usr/bin/env bash
# Exécuté SUR LE SERVEUR par GitHub Actions (voir .github/workflows/deploy.yml).
# Entrées : IMAGE_TAG (tag des images à déployer), GH_ACTOR ; le jeton GHCR arrive par l'entrée standard.
# Sauvegarde la base, déploie, attend que l'API soit saine, et revient à la version précédente sinon.
set -euo pipefail

: "${IMAGE_TAG:?IMAGE_TAG manquant}"
: "${GH_ACTOR:?GH_ACTOR manquant}"
COMPOSE=(docker compose -f docker-compose.prod.yml)
cd "$(dirname "$0")/.."

# Jeton GHCR lu sur l'entrée standard (jamais en argument : il serait visible dans la liste des processus).
read -r GHCR_TOKEN
echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GH_ACTOR" --password-stdin > /dev/null 2>&1
unset GHCR_TOKEN

PREVIOUS_TAG="$(cat .last_tag 2> /dev/null || true)"

# Sauvegarde de la base avant d'appliquer les migrations (10 dernières conservées).
mkdir -p backups
if [ -n "$("${COMPOSE[@]}" ps -q db 2> /dev/null)" ]; then
  BACKUP="backups/db-$(date +%Y%m%d-%H%M%S).sql"
  echo "Sauvegarde de la base : $BACKUP.gz"
  # < /dev/null : sans cela, exec lit l'entrée standard et peut avaler la suite du script.
  "${COMPOSE[@]}" exec -T db sh -c 'pg_dump -U hub hub' > "$BACKUP" < /dev/null
  gzip -f "$BACKUP"
  # shellcheck disable=SC2012
  ls -1t backups/db-*.sql.gz | tail -n +11 | xargs -r rm --
fi

export IMAGE_TAG
echo "Téléchargement des images (tag $IMAGE_TAG)..."
"${COMPOSE[@]}" pull

echo "Redémarrage des conteneurs..."
"${COMPOSE[@]}" down || true
"${COMPOSE[@]}" up -d

wait_healthy() {
  local id status
  for _ in $(seq 1 48); do # 48 x 5 s = 4 minutes (le temps des migrations)
    id="$("${COMPOSE[@]}" ps -q api)"
    status="$([ -n "$id" ] && docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$id" || echo none)"
    [ "$status" = "healthy" ] && return 0
    sleep 5
  done
  return 1
}

echo "Attente de l'API..."
if wait_healthy; then
  echo "$IMAGE_TAG" > .last_tag
  echo "Migrations de base de données :"
  "${COMPOSE[@]}" logs api 2>&1 | grep -iE "alembic|migrat" || true
  echo "Statut :"
  "${COMPOSE[@]}" ps
  docker image prune -f > /dev/null 2>&1 || true
  echo "Déploiement réussi ($IMAGE_TAG)."
  exit 0
fi

echo "::error::L'API n'est pas devenue saine. Derniers journaux :" >&2
"${COMPOSE[@]}" logs --tail=60 api >&2 || true
if [ -n "$PREVIOUS_TAG" ] && [ "$PREVIOUS_TAG" != "$IMAGE_TAG" ]; then
  echo "Retour automatique à la version précédente ($PREVIOUS_TAG)..." >&2
  export IMAGE_TAG="$PREVIOUS_TAG"
  "${COMPOSE[@]}" up -d || true
  echo "ATTENTION : si une migration de base a déjà été appliquée, restaurez au besoin la sauvegarde la plus récente de backups/." >&2
fi
exit 1
