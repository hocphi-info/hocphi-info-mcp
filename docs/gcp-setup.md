
## Deploying

After the variables are set, releases are a tag push:

```bash
git tag v0.1.0 && git push --tags
```

`deploy.yml` runs CI, builds the image, pushes it to Artifact Registry, deploys to Cloud
Run (`--min-instances=0 --max-instances=2`) and smoke-tests the live URL. It can also be
started by hand from the Actions tab. `smoke.yml` repeats the smoke test daily.

The service URL is `https://hocphi-info-mcp-<project number>.asia-southeast1.run.app/mcp`.
`ALLOWED_HOSTS` is set to that host automatically; a custom domain must be added to it.
