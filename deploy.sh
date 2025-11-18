#!/bin/bash

# Deploy imaging-problem-list viewer to Cloudflare Pages
# Usage: ./deploy.sh

set -e

# Configuration
PROJECT_NAME="imaging-problem-list"
DEPLOY_DIR="viewer"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Deploying ${PROJECT_NAME} to Cloudflare Pages...${NC}"

# Check if wrangler is installed locally
if [ ! -d "node_modules/wrangler" ]; then
    echo "Error: wrangler not found in node_modules"
    echo "Install with: npm install"
    exit 1
fi

# Deploy to Cloudflare Pages
echo -e "${BLUE}Deploying from ${DEPLOY_DIR}...${NC}"
npx wrangler pages deploy ${DEPLOY_DIR} \
    --project-name=${PROJECT_NAME} \
    --branch=main

echo -e "${GREEN}✓ Deployment complete!${NC}"
echo -e "View your site at: https://${PROJECT_NAME}.pages.dev"
