## Assumptions

### 1. Node Architecture

* There are 3 independent nodes.
* Each node has its own independent database.
* The state of each node can change independently from the other nodes.
* All nodes expose the same API contract.
* The client communicates with nodes exclusively through HTTP APIs.
* The client does not have direct access to the nodes' databases.

### 2. API Contract

* Group creation is performed using:
  `POST /v1/group/`
* Group deletion is performed using:
  `DELETE /v1/group/`
* Group existence is checked using:
  `GET /v1/group/{group_id}/`
* A successful `POST` returns HTTP `201 Created`.
* A successful `DELETE` returns HTTP `200 OK`.
* A successful `GET` returns HTTP `200 OK` when the group exists.
* `GET 404 Not Found` means the group does not exist on the node.
* `POST 400 Bad Request` is interpreted as the group possibly already existing.
* `DELETE 404 Not Found` is interpreted as the group not existing on the node.

### 3. Network and Error Handling

* A network/request failure may leave the result of an operation unknown.
* A `httpx.RequestError` does not guarantee that the operation was not executed on the server.
* After a network/request failure, the client's state should be verified using a `GET` request.
* HTTP status errors and network/request errors have different semantics:

  * `RequestError`: the outcome of the operation may be unknown.
  * `HTTPStatusError`: the node responded, so the outcome can be determined from the response.
* Network/request failures are retryable.
* Retries use exponential backoff.
* `max_retries` represents the number of retries after the initial attempt.
* Therefore, `max_retries=0` means exactly one attempt.
* If all retry attempts fail, the node's state may become `UNKNOWN`.

### 4. Group State

Each node can have one of three known states for a specific group:

* `FOUND`: the group is known to exist on the node.
* `NOT_FOUND`: the group is known not to exist on the node.
* `UNKNOWN`: the client cannot determine the current state of the group due to communication failures.

Additional assumptions:

* Create operations are performed on nodes whose group state is `NOT_FOUND`.
* Delete operations are performed on nodes whose group state is `FOUND`.

### 5. Create Operation

* The goal of `create_group` is to create the group on all required nodes.
* If the group already exists on all nodes, the create operation should not be performed.
* Nodes are processed sequentially.
* If creation succeeds on some nodes but fails on a subsequent node, a rollback operation is required.
* Nodes where creation was confirmed successful become rollback candidates.
* If creation fails due to a network/request error, the failed node's state is checked using `GET`.
* If the failed node is confirmed as `NOT_FOUND`, no rollback is required for that node.
* If the failed node is confirmed as `FOUND`, that node must also be included in the rollback.
* If the failed node's state is `UNKNOWN`, the rollback cannot safely determine the correct action.

### 6. Create Rollback

* Create rollback is performed by deleting the group from nodes where creation may have succeeded.
* Rollback itself may fail.
* A rollback failure may leave the system in an inconsistent state.
* Rollback operations are retried according to the configured retry policy.
* If rollback still fails after all retries, a `GroupCreateRollbackError` is raised.
* A rollback failure may require manual intervention.
* If rollback succeeds, the original create failure is reported as the primary operation failure while the system is returned to its previous state.

### 7. Delete Operation

* The goal of `delete_group` is to delete the group from all required nodes.
* If the group does not exist on a node, that node does not require deletion.
* Nodes are processed sequentially.
* If deletion succeeds on some nodes but fails on a subsequent node, a rollback operation is required.
* If deletion fails due to a network/request error, the failed node's state is checked using `GET`.
* If the failed node is confirmed as `FOUND`, no rollback is required for that node.
* If the failed node is confirmed as `NOT_FOUND`, that node must be considered for rollback.
* If the failed node's state is `UNKNOWN`, the rollback cannot safely determine the correct action.

### 8. Delete Rollback

* Delete rollback is performed by recreating the group on nodes where deletion was confirmed or is believed to have succeeded.
* Rollback itself may fail.
* A rollback failure may leave the system in an inconsistent state.
* Rollback operations are retried according to the configured retry policy.
* If rollback still fails after all retries, a `GroupDeleteRollbackError` is raised.
* A rollback failure may require manual intervention.

### 9. Consistency Model

* The client does not have a distributed transaction spanning all nodes.
* Consistency is achieved using the pattern:
  `forward operation → state verification → compensating rollback`
* A network failure does not imply that the operation failed; the actual resource state must be verified.
* The system explicitly handles the possibility of partial success across nodes.
* Rollback is a compensating operation rather than a database transaction.
* Rollback is not assumed to always succeed.
* An unresolved `UNKNOWN` state is treated as a consistency risk.
* `hard_consistency` can be used to reject situations where the required state cannot be established with certainty.
* State verification is used instead of relying solely on exceptions to determine whether an operation succeeded.
