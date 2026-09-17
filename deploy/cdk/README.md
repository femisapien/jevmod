# jevmod on AWS (CDK, Python)

Optional. A small VM with `docker compose up -d` is cheaper for one community. Use this when your team already
runs on AWS and wants secrets, logs and restarts handled by the platform.

What it creates: a VPC with public subnets only (no NAT gateway), an ECS cluster, one Fargate service (0.25 vCPU,
512 MB) per role you choose, an encrypted EFS file system holding the shared SQLite database, a CloudWatch log
group with 30-day retention, and, for the `api` role only, an Application Load Balancer with a health check on
`/v1/health`.

```bash
# 1. secrets, once (fill only what your roles need; keys as in ../../.env.example)
aws secretsmanager create-secret --name jevmod \
  --secret-string '{"TYPESAFE_API_KEY":"...","JEVMOD_ADMIN_TOKEN":"...","DISCORD_TOKEN":"..."}'

# 2. deploy
cd deploy/cdk
python -m venv .venv && .venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\pip
npm install -g aws-cdk                                                 # or use npx cdk
cdk bootstrap                                                          # first time in the account/region
cdk deploy -c roles=api,discord
```

Rough monthly cost (eu-west-1, 2026): Fargate 0.25 vCPU/512 MB about 9 $ per role, EFS under 1 $, ALB about 18 $
when you deploy the `api` role. Bots run with `min_healthy_percent=0` so a deploy never runs two copies of the same
bot at once (two copies would act twice on the same message).

Put HTTPS in front of the API before exposing it: add an ACM certificate and an HTTPS listener to the ALB in
`jevmod_stack.py`, or terminate TLS at CloudFront. Rotate `JEVMOD_ADMIN_TOKEN` by updating the secret and forcing a
new deployment of the `api` service.
