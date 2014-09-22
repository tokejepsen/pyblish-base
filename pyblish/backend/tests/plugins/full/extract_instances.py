
import pyblish


@pyblish.log
class ExtractInstances(pyblish.Extractor):
    hosts = ['python']
    families = ['full']
    version = (0, 1, 0)

    def process_instance(self, instance):
        instance.set_data('extracted', True)
