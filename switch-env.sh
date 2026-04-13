#!/usr/bin/env bash
# switch-env.sh — point the local frontend at staging or production
# Usage:  ./switch-env.sh staging
#         ./switch-env.sh production

set -e

ENV="${1:-}"
FRONTEND_DIR="$(dirname "$0")/frontend"

case "$ENV" in
  staging)
    cp "$FRONTEND_DIR/.env.staging" "$FRONTEND_DIR/.env.local"
    echo "✓ Frontend → STAGING  (https://brendanworks-staging--wcag-tester-web.modal.run)"
    ;;
  production)
    cp "$FRONTEND_DIR/.env.production" "$FRONTEND_DIR/.env.local"
    echo "✓ Frontend → PRODUCTION  (https://brendanworks--wcag-tester-web.modal.run)"
    ;;
  *)
    echo "Usage: $0 [staging|production]"
    echo ""
    echo "Current .env.local:"
    cat "$FRONTEND_DIR/.env.local" 2>/dev/null || echo "  (not set)"
    exit 1
    ;;
esac

echo "  Restart 'npm run dev' to pick up the change."
