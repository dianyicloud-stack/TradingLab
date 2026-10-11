# ACK consume isolated acceptance workspace

`test_ack_consume_isolated.py` creates a uniquely named temporary project under this directory,
copies only the required read-only inputs from the real project, and removes the temporary project
after each test. Production `state/` is never passed to `AckReceiptManager`.
