
import pyblish


@pyblish.log
class SelectInstancesError(pyblish.Selector):
    hosts = ['python']
    version = (0, 1, 0)

    def process_context(self, context):
        raise ValueError("Test exception")
