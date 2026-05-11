from agent import AgentContext
from helpers.api import ApiHandler, Request, Response
from usr.plugins.metrics.helpers.metrics_collector import collector


class MetricsDashboard(ApiHandler):

    async def process(self, input: dict, request: Request) -> dict | Response:
        action = input.get("action", "snapshot")

        if action == "snapshot":
            snap = collector.snapshot(
                from_ts=input.get("from_ts"),
                to_ts=input.get("to_ts"),
                bucket=input.get("bucket", "hour"),
            )
            _resolve_chat_names(snap)
            return {"success": True, **snap}
        return {"success": False, "error": f"Unknown action: {action}"}


def _resolve_chat_names(snap: dict) -> None:
    """Replace stale chat names with current names from live AgentContext."""
    for proj in snap.get("by_project", []):
        for chat in proj.get("chats", []):
            ctx = AgentContext.get(chat["context_id"])
            if ctx and ctx.name:
                chat["name"] = ctx.name
