import datetime
from helpers.extension import Extension


class RecordErrorMetrics(Extension):

    async def execute(self, data: dict = {}, **kwargs):
        exception = data.get("exception")
        if not exception:
            return

        from usr.plugins.metrics.helpers import correlation
        current = correlation.current_call()
        if current and current.get("recorded"):
            call_data = current.get("call_data")
            correlation.end_call(call_data if isinstance(call_data, dict) else None)
            return

        from usr.plugins.metrics.helpers.metrics_collector import collector

        agent = self.agent
        model_name = "unknown"
        provider = ""
        project = ""
        context_id = ""
        chat_name = ""
        agent_name = ""

        if agent:
            agent_name = f"Agent {agent.number}"
            try:
                model = agent.get_chat_model()
                model_name = getattr(model, "model_name", "unknown")
                model_conf = getattr(model, "a0_model_conf", None)
                provider = model_conf.provider if model_conf else ""
            except Exception:
                pass
            ctx = getattr(agent, "context", None)
            if ctx:
                context_id = getattr(ctx, "id", "")
                chat_name = getattr(ctx, "name", "")
                project = (ctx.data.get("project") if hasattr(ctx, "data") else "") or ""

        collector.record({
            "model": model_name,
            "provider": provider,
            "tokens_in": 0,
            "tokens_out": 0,
            "latency_ms": 0,
            "success": False,
            "error": str(exception),
            "stream": False,
            "attempts": 1,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "usage_type": "error",
            "agent_name": agent_name,
            "project": project,
            "context_id": context_id,
            "chat_name": chat_name,
            "source": "agent_exception",
            "tokens_source": "none",
        })
