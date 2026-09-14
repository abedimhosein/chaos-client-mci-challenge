## API consumer

## Intro

There is a cluster consisting of several nodes and, on this cluster, you create groups. For that, you need to create a record of it on all nodes via API. When you delete an object, you also need to delete it from all nodes.

The problem is that API is unstable. E.g. you can expect connection timeout or 500 errors for unknown reasons. If you got an error, then all changes should be rolled back.

You should implement a client module that will create and delete objects in the cluster as reliably as possible.

## Cluster overview

Example of a cluster configuration:

```python
HOSTS = [
'node1.example.com',
'node2.example.com',
'node3.example.com',
]
```

Each node has the same RESTfull API.

## API documentation

## Create

```
URL: /v1/group/
```
```
Method: POST
Request (application/json):
{
'groupId': str,
}
Response: 201 CREATED
Error codes:
400 - Bad request. Perhaps the object exists.
```

## Delete

```
URL: /v1/group/
```

```
Method: DELETE
Request (application/json):
{
'groupId': str
}
Response: 200 OK
```

### Get
```
URL: /v1/group/{groupId}/
```

```
Method: GET
Response (application/json):
{
'groupId': str
}
Error codes:
404 - Not found
```

## What do we expect

- Interpret, make assumptions, write it down on a README.md file.

- Write a simple documentation of how to use your code also on README.md.

- Create a Git repo on Github.

- Implement a client module to create and delete objects in a cluster as reliably as possible. httpx library is recommended.

- Write unit tests (hint: e2e tests are not required).

- Create a Docker image that executes your code (add a Containerfile or Dockerfile to your repo).

- Create some basic Kubernetes manifests of how you would deploy your client in a manifests folder. In case you don’t have experience with that you can try to apply the manifests on minikube, also Kubernetes documentation is very helpful. [URL 🔗](https://kubernetes.io/docs/home/)

- Don’t be afraid to add anything you find important for code quality.

Important note: We do not expect you to implement the cluster logic and API - it’s out of the scope of the problem. It’s supposed to use endpoints from the cluster API defined above (implement a client) to create objects on all nodes.
