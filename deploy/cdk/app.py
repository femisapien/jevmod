#!/usr/bin/env python
"""cdk deploy -c roles=api,discord   (default: api)"""

import aws_cdk as cdk
from jevmod_stack import JevmodStack

app = cdk.App()
roles = [r.strip() for r in str(app.node.try_get_context("roles") or "api").split(",") if r.strip()]
JevmodStack(app, "jevmod", roles=roles, secret_name=str(app.node.try_get_context("secret") or "jevmod"))
app.synth()
