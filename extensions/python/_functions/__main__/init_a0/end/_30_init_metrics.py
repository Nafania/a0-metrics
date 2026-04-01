from helpers.extension import Extension


class InitMetrics(Extension):

    def execute(self, **kwargs):
        from helpers import files
        from plugins._metrics.helpers.metrics_collector import collector

        path = files.get_abs_path("usr", "metrics.json")
        collector.enable_persistence(path)
