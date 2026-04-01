import time
from helpers.extension import Extension


class StampStartTime(Extension):

    async def execute(self, call_data: dict | None = None, **kwargs):
        if call_data is not None:
            call_data["_metrics_start"] = time.time()
