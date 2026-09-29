"""Relay: local-first durable background job system.

At-least-once execution with fenced leases, bounded retries and inspectable
attempt history. See docs/relay/implementation-plan.md for the design contract.
"""

from relay.sdk import Relay, Task, task
from relay.worker.ipc import report_progress as progress

__version__ = "0.2.0"
__all__ = ["Relay", "Task", "task", "progress", "__version__"]
