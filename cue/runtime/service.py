"""Task state machine: context, plan, policy-gated tools, reply, retries, approvals."""

from datetime import datetime, timedelta, timezone

from cue.runtime import context as context_builder
from cue.runtime import planner, policy, responder, scheduler, store
from cue.runtime.executor import ToolFailed, ToolRegistry, run_tool
from cue.runtime.gateway import ModelUnavailable


class TaskNotFound(LookupError):
    pass


def snapshot(task: dict, approvals: list[tuple] = ()) -> dict:
    return {
        "task_id": str(task["id"]),
        "source": task["source"],
        "status": task["status"],
        "answer": task["answer"],
        "attempts": task["attempts"],
        "approvals": [
            {"id": str(row[0]), "tool": row[1], "tier": row[2], "status": row[3]}
            for row in approvals
        ],
    }


def plan_record(plan: planner.Plan) -> dict:
    return {
        "tool_calls": [{"name": call.name, "arguments": call.arguments} for call in plan.tool_calls],
        "reply": plan.reply,
        "provider": plan.provider,
    }


def _finish(database, tenant_id, task: dict, answer: str, outbound, moment: datetime) -> dict:
    text = responder.format_reply(task, answer)
    if outbound is not None:
        outbound.send(task, text)
    store.audit(database, tenant_id, actor="cue", action="response", task_id=task["id"],
                decision="sent" if outbound is not None else "stored",
                detail={"text": answer[:1000]})
    store.set_status(database, tenant_id, task["id"], "completed", answer=answer)
    if task.get("recurrence"):
        scheduler.reschedule(database, tenant_id, task, moment)
    return snapshot(store.get_task(database, tenant_id, task["id"]),
                    store.task_approvals(database, tenant_id, task["id"]))


def _retry_or_fail(database, tenant_id, task: dict, attempts: int, moment: datetime,
                   error: str, queue, tool: str | None = None, tier: int | None = None) -> dict:
    exhausted = attempts >= task["max_attempts"]
    store.audit(database, tenant_id, actor="cue", action="retry", task_id=task["id"],
                tool=tool, tier=tier, decision="exhausted" if exhausted else "retry",
                detail={"error": error, "attempt": attempts})
    if exhausted:
        store.set_status(database, tenant_id, task["id"], "failed", error=error)
    else:
        delay = min(300, 5 * (2 ** (attempts - 1)))
        store.set_status(database, tenant_id, task["id"], "queued",
                         run_at=moment + timedelta(seconds=delay), dispatched_at=None)
        if queue is not None:
            queue.enqueue(tenant_id, task["id"], delay)
    return snapshot(store.get_task(database, tenant_id, task["id"]),
                    store.task_approvals(database, tenant_id, task["id"]))


def run_task(tenant_id, task_id, *, gateway, registry: ToolRegistry, database_url: str | None = None,
             outbound=None, memory=None, queue=None, now: datetime | None = None) -> dict:
    moment = now or datetime.now(timezone.utc)
    with store.tenant_connection(tenant_id, database_url) as database:
        task = store.get_task(database, tenant_id, task_id)
        if task is None:
            raise TaskNotFound(str(task_id))
        approvals = store.task_approvals(database, tenant_id, task_id)
        if task["status"] in {"completed", "cancelled"}:
            return snapshot(task, approvals)
        if any(row[3] == "rejected" for row in approvals):
            store.set_status(database, tenant_id, task_id, "cancelled",
                             answer="The requested action was rejected.")
            return snapshot(store.get_task(database, tenant_id, task_id), approvals)
        if any(row[3] == "pending" for row in approvals):
            return snapshot(task, approvals)

        attempts = store.bump_attempt(database, tenant_id, task_id)
        store.set_status(database, tenant_id, task_id, "running")

        participants = context_builder.participants_for(
            tenant_id, task["source"], task["channel_ref"], (), database_url)
        try:
            if memory is not None:
                context = memory(tenant_id, task["requester_uid"], task["request_text"], participants)
            else:
                context = context_builder.build_context(
                    tenant_id, task["requester_uid"], task["request_text"], participants,
                    database_url=database_url,
                )
        except (PermissionError, ValueError) as exc:
            store.audit(database, tenant_id, actor="cue", action="retry", task_id=task_id,
                        decision="exhausted", detail={"error": str(exc)})
            store.set_status(database, tenant_id, task_id, "failed", error=str(exc))
            return snapshot(store.get_task(database, tenant_id, task_id), approvals)

        try:
            plan = planner.plan(gateway, task["request_text"], context, registry.catalog())
        except (planner.PlanError, ModelUnavailable) as exc:
            return _retry_or_fail(database, tenant_id, task, attempts, moment, str(exc), queue)
        store.set_status(database, tenant_id, task_id, "running", plan=plan_record(plan))

        results = []
        for index, call in enumerate(plan.tool_calls):
            spec = registry.get(call.name)
            if spec is None:
                store.audit(database, tenant_id, actor="cue", action="tool", task_id=task_id,
                            tool=call.name, decision="rejected", detail={"error": "unknown tool"})
                store.set_status(database, tenant_id, task_id, "failed", error="Unknown tool in plan")
                return snapshot(store.get_task(database, tenant_id, task_id), approvals)

            decision = policy.decide(database, tenant_id, call.name, spec.tier, task["requester_uid"])
            store.audit(database, tenant_id, actor=task["requester_uid"], action="policy",
                        task_id=task_id, tool=call.name, tier=decision.tier,
                        decision=decision.mode, detail={"reason": decision.reason})

            if decision.forbidden:
                return _finish(database, tenant_id, task,
                               f"I can't run {call.name}: that action is prohibited.", outbound, moment)

            if decision.mode == "approve" and not store.approved(
                    database, tenant_id, task_id, call.name, call.arguments):
                approval_id = store.create_approval(
                    database, tenant_id, task_id, tool=call.name,
                    arguments=call.arguments, tier=decision.tier)
                store.set_status(database, tenant_id, task_id, "awaiting_approval")
                store.audit(database, tenant_id, actor="cue", action="approval", task_id=task_id,
                            tool=call.name, tier=decision.tier, decision="pending",
                            detail={"approval_id": str(approval_id)})
                return snapshot(store.get_task(database, tenant_id, task_id),
                                store.task_approvals(database, tenant_id, task_id))

            try:
                result, reused = run_tool(database, tenant_id, task_id, index, call, spec)
            except ToolFailed as exc:
                return _retry_or_fail(database, tenant_id, task, attempts, moment, str(exc), queue,
                                      tool=call.name, tier=decision.tier)

            store.audit(database, tenant_id, actor="cue", action="tool", task_id=task_id,
                        tool=call.name, tier=decision.tier,
                        decision="reused" if reused else "executed",
                        detail={"result": result})
            results.append({"tool": call.name, "result": result})

        answer = plan.reply if not results else responder.compose(
            gateway, task["request_text"], context, results)
        return _finish(database, tenant_id, task, answer, outbound, moment)


def decide(tenant_id, approval_id, uid: str, approved: bool, *, database_url: str | None = None,
           queue=None, now: datetime | None = None) -> dict:
    requeue = False
    with store.tenant_connection(tenant_id, database_url) as database:
        role = store.membership(database, tenant_id, uid)
        if role is None:
            raise PermissionError("Approver is not a member of this tenant")
        pending = database.execute(
            "SELECT task_id FROM agent_approvals WHERE tenant_id = %s AND id = %s AND status = 'pending'",
            (tenant_id, approval_id),
        ).fetchone()
        if pending is None:
            raise TaskNotFound("Approval not found or already decided")
        task_id = pending[0]
        requester = database.execute(
            "SELECT requester_uid FROM agent_tasks WHERE tenant_id = %s AND id = %s",
            (tenant_id, task_id),
        ).fetchone()
        if requester is None:
            raise TaskNotFound(str(task_id))
        if uid != requester[0] and role != "admin":
            raise PermissionError("Only the requester or a tenant admin can decide this action")
        decision = store.decide_approval(database, tenant_id, approval_id, uid, approved)
        if decision is None:
            raise TaskNotFound("Approval not found or already decided")
        task_id = decision["task_id"]
        store.audit(database, tenant_id, actor=uid, action="approval", task_id=task_id,
                    tool=decision["tool"], tier=decision["tier"], decision=decision["status"])
        if not approved:
            store.set_status(database, tenant_id, task_id, "cancelled",
                             answer="The requested action was rejected.")
        else:
            pending = [row for row in store.task_approvals(database, tenant_id, task_id)
                       if row[3] == "pending"]
            if not pending:
                store.set_status(database, tenant_id, task_id, "queued",
                                 run_at=now or datetime.now(timezone.utc), dispatched_at=None)
                requeue = True
        task = store.get_task(database, tenant_id, task_id)
        approvals = store.task_approvals(database, tenant_id, task_id)
    if requeue and queue is not None:
        queue.enqueue(tenant_id, task_id)
    return snapshot(task, approvals)
