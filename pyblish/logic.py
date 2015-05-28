"""Shared processing logic"""

import sys
import traceback

import pyblish
from plugin import Provider


class TestFailed(Exception):
    def __init__(self, msg, vars):
        super(TestFailed, self).__init__(msg)
        self.vars = vars


def default_test(**vars):
    r"""Evaluate whether or not to continue processing

    The test determines whether or not to proceed from one
    plug-in to the next. The `vars` are updated everytime
    a plug-in is about to be processed with information about
    the upcoming plug-in.

    You can provide your own test by registering it, see example below.

    Variables:
        order (int): Order of next plugin
        errorOrders (list): Orders at which an error has occured

    """

    if vars["order"] >= 2:  # If validation is done
        for order in vars["errorOrders"]:
            if order < 2:  # Were there any error before validation?
                return False
    return True


def process(func, plugins, context, test=None):
    r"""Primary processing logic

    Takes callables and data as input, and performs
    logical operations on them until the currently
    registered test fails.

    If `plugins` is a callable, it is called early, before
    processing begins. If `context` is a callable, it will
    be called once per plug-in.

    Arguments:
        func (callable): Callable taking three arguments;
             plugin(Plugin), context(Context) and optional
             instance(Instance). Each must provide a matching
             interface to their corresponding objects.
        plugins (list, callable): Plug-ins to process. If a
            callable is provided, the return value is used
            as plug-ins. It is called with no arguments.
        context (Context, callable): Context whose instances
            are to be processed. If a callable is provided,
            the return value is used as context. It is called
            with no arguments.
        test (callable, optional): Provide custom test, defaults
            to the currently registered test.

    Yields:
        A result per complete process. If test fails,
        a TestFailed exception is returned, containing the
        variables used in the test. Finally, any exception
        thrown by `process` is yielded. Note that this is
        considered a bug in *your* code as you are the one
        supplying it.

    Example:
        >>> import pyblish.api
        >>> import pyblish.plugin
        >>>
        >>> context = pyblish.api.Context()
        >>> provider = pyblish.plugin.Provider()
        >>>
        >>> def my_process(plugin, context, instance=None):
        ...   result = {
        ...     "success": False,
        ...     "plugin": plugin,
        ...     "instance": instance,
        ...     "error": None,
        ...     "records": list(),
        ...     "duration": None
        ...   }
        ...   plugin = plugin()
        ...   provider.inject("context", context)
        ...   provider.inject("instance", instance)
        ...   provider.invoke(plugin.process)
        ...   return result
        ...
        >>> class SelectInstance(pyblish.api.Selector):
        ...   def process(self, context):
        ...     context.create_instance("MyInstance")
        ...
        >>> for result in process(
        ...         plugins=[SelectInstance],
        ...         func=my_process,
        ...         context=context):
        ...     assert not isinstance(result, TestFailed)
        ...
        >>> len(context) == 1
        True

    """

    __plugins = plugins
    __context = context

    if test is None:
        test = registered_test()

    if hasattr(__plugins, "__call__"):
        plugins = __plugins()

    def gen(instances):
        """Generate pair of context/instance"""
        if len(instances) > 0:
            for instance in instances:
                yield instance
        else:
            yield None

    vars = {
        "order": None,
        "errorOrders": list()
    }

    # Clear introspection values
    self = sys.modules[__name__]
    self.process.next_plugin = None
    self.process.next_instance = None

    for plugin in plugins:
        vars["order"] = plugin.order

        if test(**vars):
            if hasattr(__context, "__call__"):
                context = __context()

            instances = instances_by_plugin(context, plugin)
            # Process once, regardless of available instances if
            # plug-in isn't associated with any particular family.
            if not instances and "*" not in plugin.families:
                continue

            for instance in gen(instances):

                # Provide introspection
                self.process.next_instance = instance
                self.process.next_plugin = plugin

                try:
                    result = func(plugin, context, instance)

                except Exception as exception:
                    # If this happens, there is a bug
                    _extract_traceback(exception)
                    yield exception

                else:
                    # Make note of the order at which
                    # the potential error error occured.
                    if result["error"]:
                        if plugin.order not in vars["errorOrders"]:
                            vars["errorOrders"].append(plugin.order)
                    yield result

                # If the plug-in doesn't have a compatible instance,
                # and the context isn't being processed, discard plug-in.
                args = Provider.args(plugin.process)
                if "instance" not in args:
                    break

        else:
            yield TestFailed("Test failed", vars)
            break


process.next_plugin = None
process.next_instance = None


def register_test(test):
    """Register test used to determine when to abort processing

    Arguments:
        test (callable): Called with argument `vars` and returns
            either True or False. True means to continue,
            False to abort.

    Example:
        >>> # Register custom test
        >>> def my_test(**vars):
        ...   return 1
        ...
        >>> register_test(my_test)
        >>>
        >>> # Run test
        >>> if my_test(order=1, errorOrders=[]):
        ...   print("Test passed")
        Test passed
        >>>
        >>> # Restore default
        >>> deregister_test()

    """

    pyblish._registered_test = test


def registered_test():
    """Return the currently registered test"""
    return pyblish._registered_test


def deregister_test():
    """Restore default test"""
    register_test(default_test)


def plugins_by_family(plugins, family):
    """Return compatible plugins `plugins` to family `family`

    Arguments:
        plugins (list): List of plugins
        family (str): Family with which to compare against

    Returns:
        List of compatible plugins.

    """

    compatible = list()

    for plugin in plugins:
        if not hasattr(plugin, "families"):
            continue

        if any(x in plugin.families for x in (family, "*")):
            compatible.append(plugin)

    return compatible


def plugins_by_instance(plugins, instance):
    """Conveinence function for :func:`plugins_by_family`

    Arguments:
        plugins (list): Plug-ins to assess
        instance (Instance): Instance with which to compare against

    Returns:
        List of compatible plugins

    """

    return plugins_by_family(plugins, instance.data("family"))


def plugins_by_host(plugins, host):
    """Return compatible plugins `plugins` to host `host`

    Arguments:
        plugins (list): List of plugins
        host (str): Host with which compatible plugins are returned

    Returns:
        List of compatible plugins.

    """

    compatible = list()

    for plugin in plugins:
        if not hasattr(plugin, "hosts"):
            continue

        # TODO(marcus): Expand to take partial wildcards e.g. "*Mesh"
        if any(x in plugin.hosts for x in (host, "*")):
            compatible.append(plugin)

    return compatible


def instances_by_plugin(instances, plugin):
    """Return compatible instances `instances` to plugin `plugin`

    Arguments:
        instances (list): List of instances
        plugin (Plugin): Plugin with which to compare against

    Returns:
        List of compatible instances

    Invariant:
        Order of remaining plug-ins must remain the same

    """

    compatible = list()

    for instance in instances:
        if not hasattr(plugin, "families"):
            continue

        family = instance.data("family")
        if any(x in plugin.families for x in (family, "*")):
            compatible.append(instance)

    return compatible


def _extract_traceback(exception):
    try:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        exception.traceback = traceback.extract_tb(exc_traceback)[-1]

    except:
        pass

    finally:
        del(exc_type, exc_value, exc_traceback)


if __name__ == '__main__':
    import doctest
    doctest.testmod()
