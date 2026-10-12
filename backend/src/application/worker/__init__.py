"""The call worker package: taskiq tasks, the handoff registry, the runner.

Deliberately no eager imports — three processes import parts of this package
with very different weights:

* the hooks controller needs ``registry`` (redis only);
* the taskiq worker/scheduler load ``tasks`` (telephony adapters → pipecat);
* the hooks lifespan imports the *runner* to warm the engine before serving.

Import the module you mean; an eager ``__init__`` would make the lightest
consumer pay for the heaviest import.
"""
