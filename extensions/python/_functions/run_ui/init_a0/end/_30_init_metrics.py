from helpers.extension import Extension


class InitMetrics(Extension):

    def execute(self, **kwargs):
        from helpers import files, plugins
        from usr.plugins.metrics.helpers.metrics_collector import collector

        config = plugins.get_plugin_config("metrics") or {}

        ring_buffer_size = config.get("ring_buffer_size", 2000)
        flush_interval = config.get("flush_interval_seconds", 30.0)
        collector.configure(maxlen=ring_buffer_size, flush_interval=flush_interval)

        persistence_file = config.get("persistence_file", "usr/metrics.json")
        path = files.get_abs_path(*persistence_file.split("/"))
        collector.enable_persistence(path)
