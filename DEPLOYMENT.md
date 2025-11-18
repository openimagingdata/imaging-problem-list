# Deployment Guide

## Cloudflare Pages Deployment

The viewer is deployed as a static site on Cloudflare Pages.

### Initial Setup

1. **Install dependencies** (including Wrangler CLI):
   ```bash
   npm install
   ```

2. **Authenticate with Cloudflare**:
   ```bash
   npx wrangler login
   ```
   This will open a browser window to authorize the CLI.

3. **First Deployment**:
   ```bash
   ./deploy.sh
   # OR
   npm run deploy
   ```

   The first time you run this, it will create a new Cloudflare Pages project named `imaging-problem-list`.

### Updating the Site

Simply run the deployment script whenever you want to update:

```bash
./deploy.sh
# OR
npm run deploy
```

This will:
- Deploy the entire `viewer/` directory to Cloudflare Pages
- Update the live site immediately
- Provide a URL to view the deployed site

### Site URL

After deployment, your site will be available at:
- **Production**: `https://imaging-problem-list.pages.dev`
- **Custom domain**: Can be configured in Cloudflare Pages dashboard

### Updating Data

To update patient data:

1. Modify files in `viewer/data/`
2. Run `./deploy.sh`

The entire viewer directory (including data) will be redeployed.

### Cloudflare Pages Dashboard

Access advanced settings and analytics:
1. Go to https://dash.cloudflare.com/
2. Select "Workers & Pages"
3. Click on "imaging-problem-list"

Here you can:
- Set up custom domains
- View deployment history
- Configure environment variables
- Set up preview deployments
- View analytics

### Automatic Deployments via GitHub

To set up automatic deployments when you push to GitHub:

1. In Cloudflare Pages dashboard, click "Connect to Git"
2. Authorize Cloudflare to access your GitHub repository
3. Select this repository
4. Configure build settings:
   - **Build command**: (leave empty - no build needed)
   - **Build output directory**: `viewer`
   - **Root directory**: `/`
5. Save and deploy

After this setup, every push to the main branch will automatically trigger a deployment.

### Manual Deployment via Wrangler

If you prefer not to use the script:

```bash
npx wrangler pages deploy viewer --project-name=imaging-problem-list
```

### Advanced Configuration (Optional)

For custom headers, redirects, or other advanced features, you can create a `_headers` or `_redirects` file in the `viewer/` directory. See [Cloudflare Pages documentation](https://developers.cloudflare.com/pages/configuration/) for details.

### Environment-Specific Deployments

Deploy to a preview branch:
```bash
wrangler pages deploy viewer --project-name=imaging-problem-list --branch=preview
```

This creates a separate deployment at a URL like:
`https://preview.imaging-problem-list.pages.dev`

### Troubleshooting

**Error: "wrangler not found"**
- Install dependencies: `npm install`

**Error: "Not authenticated"**
- Run `wrangler login` and complete authentication

**Changes not appearing**
- Cloudflare Pages uses aggressive caching. Try:
  - Hard refresh (Cmd+Shift+R on Mac, Ctrl+F5 on Windows)
  - Check deployment succeeded in dashboard
  - Wait 1-2 minutes for CDN propagation

**Large data directory**
- Cloudflare Pages has a 25MB file size limit per file
- Total project size limit is 25MB for free tier
- If needed, consider moving data to Cloudflare R2 or another storage service
