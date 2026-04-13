#!/usr/bin/env bash
# deploy.sh — deploy to staging or production
# Usage:  ./deploy.sh staging
#         ./deploy.sh production

set -e

ENV="${1:-}"

case "$ENV" in
  staging)
    echo "▶ Deploying to STAGING..."
    modal deploy --env staging modal_app.py
    echo "✓ Staging deploy complete."
    echo "  Backend:  https://brendanworks-staging--wcag-tester-web.modal.run"
    echo "  Logs:     modal app logs --env staging wcag-tester --follow"
    ;;
  production)
    echo "▶ Deploying to PRODUCTION..."
    modal deploy modal_app.py
    echo "✓ Production deploy complete."
    echo "  Backend:  https://brendanworks--wcag-tester-web.modal.run"
    echo "  Logs:     modal app logs wcag-tester --follow"
    ;;
  *)
    echo "Usage: $0 [staging|production]"
    exit 1
    ;;
esac
