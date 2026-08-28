// ECS Trust Graph v2 — Cedar policies
// Graph (NetworkX) supplies facts in context; Cedar decides permit/forbid.
// Forbid always wins.

@id("start-task")
permit (
  principal is User,
  action == Action::"StartTask",
  resource is Pack
) when {
  context.has_grant &&
  context.user_active &&
  context.entry == context.pack_entry &&
  context.env == context.pack_env
};

@id("hop")
permit (
  principal is Agent,
  action == Action::"Hop",
  resource is Agent
) when {
  context.invoke_edge &&
  context.both_in_pack &&
  context.task_active
};

@id("egress-query")
permit (
  principal is ServicePrincipal,
  action == Action::"query",
  resource is Resource
) when {
  context.task_active &&
  context.actor_in_snapshot_egress &&
  context.sp_binds_actor &&
  context.sp_access_edge &&
  context.resource_in_snapshot &&
  context.action_in_snapshot &&
  context.data_ok &&
  context.risk_ok &&
  context.amount_ok
};

@id("egress-submit")
permit (
  principal is ServicePrincipal,
  action == Action::"submit",
  resource is Resource
) when {
  context.task_active &&
  context.actor_in_snapshot_egress &&
  context.sp_binds_actor &&
  context.sp_access_edge &&
  context.resource_in_snapshot &&
  context.action_in_snapshot &&
  context.data_ok &&
  context.risk_ok &&
  context.amount_ok
};

@id("forbid-inactive-user")
forbid (
  principal is User,
  action == Action::"StartTask",
  resource is Pack
) when { !context.user_active };

@id("forbid-worker-egress")
forbid (
  principal is ServicePrincipal,
  action in [Action::"query", Action::"submit"],
  resource is Resource
) when { !context.actor_in_snapshot_egress };

@id("forbid-no-sp-edge")
forbid (
  principal is ServicePrincipal,
  action in [Action::"query", Action::"submit"],
  resource is Resource
) when { !context.sp_access_edge };

@id("forbid-not-entitled")
forbid (
  principal is ServicePrincipal,
  action in [Action::"query", Action::"submit"],
  resource is Resource
) when { !context.resource_in_snapshot || !context.action_in_snapshot };

@id("forbid-no-data-right")
forbid (
  principal is ServicePrincipal,
  action in [Action::"query", Action::"submit"],
  resource is Resource
) when { !context.data_ok };

@id("forbid-amount-over-cap")
forbid (
  principal is ServicePrincipal,
  action in [Action::"query", Action::"submit"],
  resource is Resource
) when { !context.amount_ok };

@id("forbid-risk")
forbid (
  principal is ServicePrincipal,
  action in [Action::"query", Action::"submit"],
  resource is Resource
) when { !context.risk_ok };

@id("forbid-l5")
forbid (
  principal is ServicePrincipal,
  action in [Action::"query", Action::"submit"],
  resource is Resource
) when { context.risk_rank >= 5 };

@id("forbid-dead-task")
forbid (
  principal is ServicePrincipal,
  action in [Action::"query", Action::"submit"],
  resource is Resource
) when { !context.task_active };
