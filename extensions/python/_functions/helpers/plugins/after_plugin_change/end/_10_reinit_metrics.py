from helpers.extension import Extension


class ReinitMetrics(Extension):
    """Reinitialize metrics collector after Agent Zero purges usr.plugins.* namespace.

    helpers.plugins.after_plugin_change calls modules.purge_namespace("usr.plugins")
    on any plugin change with python_change=True. That destroys the metrics_collector
    singleton along with its persistence binding. Without this hook, the next
    dashboard request would create an empty singleton (no persistence) and stay
    empty until a new Agent is created (which fires agent_init).

    This extension runs at the end of after_plugin_change, re-imports the (freshly
    re-created) collector module, and re-attaches persistence so the dashboard sees
    the events again immediately.
    """

    def execute(self, **kwargs):
        from usr.plugins.metrics.helpers.init import initialize
        initialize()
