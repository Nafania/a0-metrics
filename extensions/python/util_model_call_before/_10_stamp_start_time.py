import time
from helpers.extension import Extension


class StampStartTime(Extension):

    async def execute(self, call_data: dict | None = None, **kwargs):
        if call_data is None:
            return

        call_data["_metrics_start"] = time.time()

        original_cb = call_data.get("callback")
        if original_cb:
            async def _ttft_wrapper(chunk: str):
                if "_metrics_ttft" not in call_data:
                    call_data["_metrics_ttft"] = time.time()
                await original_cb(chunk)
            call_data["callback"] = _ttft_wrapper
