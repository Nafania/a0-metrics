import datetime
import time
from helpers.extension import Extension
from helpers.tokens import approximate_tokens


class RecordUtilMetrics(Extension):

    async def execute(
        self,
        call_data: dict | None = None,
        response: str = "",
        **kwargs,
    ):
        if call_data is None:
            return

        from plugins._metrics.helpers.metrics_collector import collector

        start = call_data.get("_metrics_start")
        latency_ms = int((time.time() - start) * 1000) if start else 0

        model = call_data.get("model")
        model_name = getattr(model, "model_name", "unknown") if model else "unknown"
        model_conf = getattr(model, "a0_model_conf", None)
        provider = model_conf.provider if model_conf else ""

        system = call_data.get("system", "")
        message = call_data.get("message", "")
        tokens_in = approximate_tokens(system) + approximate_tokens(message)
        tokens_out = approximate_tokens(response)

        agent = self.agent
        project = ""
        context_id = ""
        chat_name = ""
        agent_name = ""
        if agent:
            agent_name = f"Agent {agent.number}"
            ctx = getattr(agent, "context", None)
            if ctx:
                context_id = getattr(ctx, "id", "")
                chat_name = getattr(ctx, "name", "")
                project = getattr(ctx, "project", "") or ""

        collector.record({
            "model": model_name,
            "provider": provider,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": latency_ms,
            "success": True,
            "stream": call_data.get("callback") is not None,
            "attempts": 1,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "usage_type": "utility",
            "agent_name": agent_name,
            "project": project,
            "context_id": context_id,
            "chat_name": chat_name,
        })
