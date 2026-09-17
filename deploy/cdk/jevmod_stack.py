"""jevmod on AWS: one Fargate service per role, SQLite on EFS, secrets in Secrets Manager, logs in CloudWatch.

    cd deploy/cdk && pip install -r requirements.txt
    cdk deploy -c roles=api,discord            # roles: api | discord | telegram | reddit (comma separated)

Secrets are read from one Secrets Manager secret named `jevmod` with JSON keys matching .env.example
(TYPESAFE_API_KEY, JEVMOD_ADMIN_TOKEN, DISCORD_TOKEN, TELEGRAM_TOKEN, REDDIT_*). Create it once:

    aws secretsmanager create-secret --name jevmod --secret-string '{"TYPESAFE_API_KEY":"...","JEVMOD_ADMIN_TOKEN":"..."}'

Sizing: 0.25 vCPU / 512 MB per role is plenty; the judge is I/O bound and batches per tenant.
Cost: about 10 $/month per role for Fargate plus EFS and, for the api role, an ALB (~18 $/month). A single small VM
with docker compose is cheaper for one community; this stack is for teams that already live on AWS.
"""

from __future__ import annotations

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_efs as efs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as sm
from constructs import Construct

ROLES = ("api", "discord", "telegram", "reddit")
SECRET_KEYS = {
    "api": ["TYPESAFE_API_KEY", "JEVMOD_ADMIN_TOKEN"],
    "discord": ["TYPESAFE_API_KEY", "DISCORD_TOKEN"],
    "telegram": ["TYPESAFE_API_KEY", "TELEGRAM_TOKEN"],
    "reddit": [
        "TYPESAFE_API_KEY",
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "REDDIT_USERNAME",
        "REDDIT_PASSWORD",
        "REDDIT_SUBREDDITS",
    ],
}


class JevmodStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, roles: list[str], secret_name: str = "jevmod") -> None:
        super().__init__(scope, construct_id)
        unknown = set(roles) - set(ROLES)
        if unknown:
            raise ValueError(f"unknown roles {sorted(unknown)}; use {', '.join(ROLES)}")

        # Public subnets only (no NAT gateway: ~32 $/month saved); tasks get public IPs and reach Jev/Discord directly.
        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC)],
        )
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc, container_insights=False)
        secret = sm.Secret.from_secret_name_v2(self, "Secret", secret_name)
        log_group = logs.LogGroup(
            self, "Logs", retention=logs.RetentionDays.ONE_MONTH, removal_policy=RemovalPolicy.DESTROY
        )

        # One EFS file system shared by every role: all roles read and write the same SQLite file.
        fs = efs.FileSystem(
            self,
            "Data",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            encrypted=True,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_policy=efs.LifecyclePolicy.AFTER_30_DAYS,
        )
        access_point = fs.add_access_point(
            "Ap",
            path="/jevmod",
            create_acl=efs.Acl(owner_uid="1000", owner_gid="1000", permissions="750"),
            posix_user=efs.PosixUser(uid="1000", gid="1000"),
        )
        image = ecs.ContainerImage.from_asset("../..")  # the repository root Dockerfile

        for role in roles:
            task = ecs.FargateTaskDefinition(self, f"Task-{role}", cpu=256, memory_limit_mib=512)
            task.add_volume(
                name="data",
                efs_volume_configuration=ecs.EfsVolumeConfiguration(
                    file_system_id=fs.file_system_id,
                    transit_encryption="ENABLED",
                    authorization_config=ecs.AuthorizationConfig(
                        access_point_id=access_point.access_point_id, iam="ENABLED"
                    ),
                ),
            )
            fs.grant_read_write(task.task_role)
            container = task.add_container(
                role,
                image=image,
                environment={"JEVMOD_ROLE": role, "JEVMOD_DB": "/data/jevmod.sqlite", "PORT": "8080"},
                secrets={k: ecs.Secret.from_secrets_manager(secret, k) for k in SECRET_KEYS[role]},
                logging=ecs.LogDrivers.aws_logs(stream_prefix=role, log_group=log_group),
                port_mappings=[ecs.PortMapping(container_port=8080)] if role == "api" else None,
            )
            container.add_mount_points(ecs.MountPoint(container_path="/data", source_volume="data", read_only=False))

            service = ecs.FargateService(
                self,
                f"Service-{role}",
                cluster=cluster,
                task_definition=task,
                desired_count=1,
                assign_public_ip=True,
                min_healthy_percent=0,  # bots must not run twice (double actions); api can afford a blip
                max_healthy_percent=100,
                circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            )
            fs.connections.allow_default_port_from(service)

            if role == "api":
                alb = elbv2.ApplicationLoadBalancer(self, "Alb", vpc=vpc, internet_facing=True)
                listener = alb.add_listener("Http", port=80)  # put an ACM certificate + HTTPS listener in front
                listener.add_targets(
                    "Api",
                    port=8080,
                    targets=[service],
                    health_check=elbv2.HealthCheck(path="/v1/health", interval=Duration.seconds(30)),
                    deregistration_delay=Duration.seconds(10),
                )
                self.api_url = f"http://{alb.load_balancer_dns_name}"
