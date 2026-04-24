from helpers.extension import Extension


class InitMetrics(Extension):

    def execute(self, **kwargs):
        from usr.plugins.metrics.helpers.init import initialize
        initialize()
