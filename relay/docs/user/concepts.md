# Concepts and failure model

## Jobs, attempts, leases

A job describes work in a named queue. Each claim creates an attempt with a lease
and fencing token. The worker renews its lease while supervising a spawned child.
A completion is accepted only from the current owner; a late child cannot overwrite
a newer attempt's database state.

Queues can pause new claims without stopping attempts already running. Retry policy
and scheduled availability affect when work becomes eligible. Cancellation is a
request, not a guarantee that an external effect has been undone.

## Delivery is not exactly once

A process can perform an external effect and crash before recording completion.
Lease recovery can run that work again. Use effect-level idempotency in handlers;
an idempotency key on submission does not make third-party operations transactional.
SQLite transactions protect local records, not external systems.

Pruning old terminal jobs also removes their submission idempotency protection.
Treat retention as a behavioral decision, not just disk cleanup.

## Process and deployment limits

Workers use separate spawned child processes and bounded supervision. They run
trusted registered code, not user-supplied import paths or a general sandbox.
Watchdog termination is not a promise to kill arbitrary descendants or roll back
filesystem/network effects. API availability and worker availability are distinct.

One installation uses one SQLite database on local storage. Remote deployment,
multi-host workers, active-active failover, and hostile tenants are outside this
snapshot's supported boundary.
