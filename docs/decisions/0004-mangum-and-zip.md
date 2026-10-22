# 0004. Mangum and a zip bundle for the Lambda functions

Date: 2026-10-21 · Status: Accepted

## Context

The FastAPI app runs on Lambda behind an HTTP API. A second function, the job worker, runs on EventBridge events
and direct invokes, with no HTTP layer. The backend is a uv project, and scikit-learn (with NumPy and SciPy) is
only used by `evaluation/`. A zip package is limited to 250 MB unzipped.

## Decision

- **Adapter.** Mangum wraps the ASGI app in-process (`handler = Mangum(app)`). The worker is a plain handler in
  the same package.
- **Packaging.** One zip for arm64 and Python 3.12, built by `infra/scripts/bundle-api.ts` with
  `uv export --frozen --no-dev` and `uv pip install --target --python-platform aarch64-manylinux2014
  --only-binary :all:`, plus the package source. Both functions use it.
- **scikit-learn.** It moves to an `eval` dependency group, listed in `[tool.uv] default-groups` so local
  `uv sync` and `uv run eval` behave as before. The bundle leaves it out.
- **Client IP.** Rate limiting reads it from the API Gateway request context that Mangum passes through, never
  from `X-Forwarded-For`.

## Consequences

- **Tests.** The handlers can be tested offline with recorded API Gateway v2 events.
- **Layering.** The import layering test also guards the bundle: nothing the API or the worker imports may need
  scikit-learn.
- **Deploying.** A deploy needs uv on the machine running `cdk deploy`, and network access to PyPI.
- **Maintenance.** Mangum releases are infrequent: 0.20.0 in December 2025 and 0.21.0 in February 2026, after a
  gap of over a year. Replacing it would touch one module.

## Alternatives considered

- **AWS Lambda Web Adapter.** Runs uvicorn unchanged and supports response streaming, which we don't use. It
  delivers non-HTTP events as a POST to `/events`, which would put the worker behind an HTTP route, and adds a
  per-Region layer ARN.
- **A container image.** No size limit, but it adds ECR and a Docker build to every deploy. The zip fits once
  scikit-learn is out.
