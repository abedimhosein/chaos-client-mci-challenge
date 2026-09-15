import unittest
from http import HTTPStatus
from unittest.mock import patch

import httpx

from app.client import NodeAdapter, Orchestrator, OrchestratorConfig
from app.exceptions import (
    GroupCreateError,
    GroupDeleteError,
    NodeGroupNotFoundError,
    NodeGroupPerhapsAlreadyExistsError,
    NodeHTTPStatusError,
    NodeRequestError,
    GroupCreateRollbackError,
    UnknownNodeStateError,
)
from app.models import Group, Node


class NodeAdapterTests(unittest.TestCase):
    """
    NodeAdapterTests verifies that errors and HTTP responses are correctly
    converted into domain exceptions.
    """

    def make_adapter(self, handler) -> NodeAdapter:
        return NodeAdapter(
            node=Node("http://node1.example.com"),
            timeout=1,
            transport=httpx.MockTransport(handler=handler),
        )

    def make_handler(self, status):
        return lambda request: httpx.Response(status, request=request)

    def test_get_group_maps_404_to_not_found(self):
        """Maps 404 from get_group to NodeGroupNotFoundError."""
        adapter = self.make_adapter(handler=self.make_handler(HTTPStatus.NOT_FOUND))
        self.addCleanup(adapter.close)

        with self.assertRaises(NodeGroupNotFoundError):
            adapter.get_group(Group("G1"))

    def test_create_group_maps_400_to_already_exists(self):
        """Maps 400 from create_group to NodeGroupPerhapsAlreadyExistsError."""
        adapter = self.make_adapter(self.make_handler(HTTPStatus.BAD_REQUEST))
        self.addCleanup(adapter.close)

        with self.assertRaises(NodeGroupPerhapsAlreadyExistsError):
            adapter.create_group(Group("G1"))

    def test_non_special_http_error_is_preserved(self):
        """Preserves the status code in NodeHTTPStatusError."""

        adapter = self.make_adapter(self.make_handler(HTTPStatus.INTERNAL_SERVER_ERROR))
        self.addCleanup(adapter.close)

        with self.assertRaises(NodeHTTPStatusError) as raised:
            adapter.get_group(Group("G1"))

        self.assertEqual(raised.exception.status_code, HTTPStatus.INTERNAL_SERVER_ERROR)

    def test_request_error_is_wrapped(self):
        def make_handler(request):
            raise httpx.RequestError("unavailable", request=request)

        adapter = self.make_adapter(make_handler)
        self.addCleanup(adapter.close)

        with self.assertRaises(NodeRequestError):
            adapter.get_group(Group("G1"))


class OrchestratorTests(unittest.TestCase):
    def make_orchestrator(self, handlers, max_retries=0) -> Orchestrator:
        handlers = list(handlers)
        handler_iterator = iter(handlers)

        def adapter_factory(node, timeout):
            return NodeAdapter(
                node,
                timeout,
                transport=httpx.MockTransport(next(handler_iterator)),
            )

        return Orchestrator(
            [Node(f"http://node-{index}.example.com") for index in range(1, len(handlers) + 1)],
            OrchestratorConfig(max_retries=max_retries, timeout=1, backoff=0),
            adapter_factory=adapter_factory,
        )

    def test_create_group(self):
        """Test happy path for creating groups"""

        groups = set()
        actual_calls = []
        desired_calls = [
            ("node-1.example.com", "GET", "/v1/group/G1/"),
            ("node-2.example.com", "GET", "/v1/group/G1/"),
            ("node-1.example.com", "POST", "/v1/group/"),
            ("node-2.example.com", "POST", "/v1/group/"),
        ]

        def handler(request):
            actual_calls.append((request.url.host, request.method, request.url.path))

            if request.method == "GET":
                status = HTTPStatus.OK if request.url.host in groups else HTTPStatus.NOT_FOUND
                return httpx.Response(status, request=request)

            if request.method == "POST":
                groups.add(request.url.host)
                return httpx.Response(HTTPStatus.CREATED, request=request)

            return httpx.Response(HTTPStatus.METHOD_NOT_ALLOWED, request=request)

        with self.make_orchestrator([handler, handler]) as orchestrator:
            orchestrator.create_group(Group("G1"))

        self.assertEqual(actual_calls, desired_calls)

    def test_delete_group(self):
        """Test happy path for deleting groups."""

        groups = {
            "node-1.example.com",
            "node-2.example.com",
        }
        actual_calls = []
        desired_calls = [
            ("node-1.example.com", "GET", "/v1/group/G1/"),
            ("node-2.example.com", "GET", "/v1/group/G1/"),
            ("node-1.example.com", "DELETE", "/v1/group/"),
            ("node-2.example.com", "DELETE", "/v1/group/"),
        ]

        def handler(request):
            actual_calls.append((request.url.host, request.method, request.url.path))

            if request.method == "GET":
                status = HTTPStatus.OK if request.url.host in groups else HTTPStatus.NOT_FOUND
                return httpx.Response(status, request=request)

            if request.method == "DELETE":
                groups.discard(request.url.host)
                return httpx.Response(HTTPStatus.OK, request=request)

            return httpx.Response(HTTPStatus.METHOD_NOT_ALLOWED, request=request)

        with self.make_orchestrator([handler, handler]) as orchestrator:
            orchestrator.delete_group(Group("G1"))

        self.assertEqual(actual_calls, desired_calls)

    def test_create_failure_rolls_back_successful(self):
        """Test rollback of successfully created groups after a node failure."""

        node_1_groups = set()
        node_2_groups = set()

        node_1_calls = []
        node_2_calls = []

        def node_1_handler(request):
            node_1_calls.append(request.method)

            if request.method == "GET":
                status = HTTPStatus.OK if "G1" in node_1_groups else HTTPStatus.NOT_FOUND
                return httpx.Response(status, request=request)

            if request.method == "POST":
                node_1_groups.add("G1")
                return httpx.Response(HTTPStatus.CREATED, request=request)

            if request.method == "DELETE":
                node_1_groups.discard("G1")
                return httpx.Response(HTTPStatus.OK, request=request)

            return httpx.Response(HTTPStatus.METHOD_NOT_ALLOWED, request=request)

        def node_2_handler(request):
            node_2_calls.append(request.method)

            if request.method == "GET":
                status = HTTPStatus.OK if "G1" in node_2_groups else HTTPStatus.NOT_FOUND
                return httpx.Response(status, request=request)

            if request.method == "POST":
                raise httpx.ConnectError("node unavailable", request=request)

            return httpx.Response(HTTPStatus.METHOD_NOT_ALLOWED, request=request)

        with self.make_orchestrator([node_1_handler, node_2_handler]) as orchestrator:
            with patch("app.client.logger.error"):  # for silent the logger
                with self.assertRaises(GroupCreateError):
                    orchestrator.create_group(Group("G1"))

        self.assertEqual(node_1_calls, ["GET", "POST", "DELETE"])
        self.assertEqual(node_2_calls, ["GET", "POST", "GET"])

        self.assertNotIn("G1", node_1_groups)
        self.assertNotIn("G1", node_2_groups)

    def test_create_retries_connection_error(self):
        attempts = []

        def handler(request):
            attempts.append(request.method)

            if request.method == "GET":
                return httpx.Response(HTTPStatus.NOT_FOUND, request=request)

            if request.method == "POST" and len([attempt for attempt in attempts if attempt == "POST"]) == 1:
                raise httpx.ConnectError("temporary", request=request)

            return httpx.Response(HTTPStatus.NO_CONTENT, request=request)

        with self.make_orchestrator([handler], max_retries=1) as orchestrator:
            orchestrator.create_group(Group("G1"))

        self.assertEqual(attempts, ["GET", "POST", "POST"])

    def test_unknown_state_aborts_create(self):
        def handler(request):
            raise httpx.ConnectError("unavailable", request=request)

        with self.make_orchestrator([handler]) as orchestrator:
            with self.assertRaises(UnknownNodeStateError):
                orchestrator.create_group(Group("G1"))

    def test_delete_failure_rolls_back_successful(self):
        node_1_calls = []
        node_2_calls = []

        def node_1_handler(request):
            node_1_calls.append(request.method)

            if request.method == "GET":
                return httpx.Response(HTTPStatus.OK, request=request)

            return httpx.Response(HTTPStatus.NO_CONTENT, request=request)

        def node_2_handler(request):
            node_2_calls.append(request.method)

            if request.method == "GET":
                return httpx.Response(HTTPStatus.OK, request=request)

            raise httpx.ConnectError("unavailable", request=request)

        with self.make_orchestrator([node_1_handler, node_2_handler]) as orchestrator:
            with patch("app.client.logger.error"):  # for silent the logger
                with self.assertRaises(GroupDeleteError):
                    orchestrator.delete_group(Group("G1"))

        self.assertEqual(node_1_calls, ["GET", "DELETE", "POST"])
        self.assertEqual(node_2_calls, ["GET", "DELETE", "GET"])

    def test_create_failure_rolls_back_failure(self):
        """Test create failure when rollback also fails."""

        node_1_groups = set()
        node_2_groups = set()

        node_1_calls = []
        node_2_calls = []

        def node_1_handler(request):
            node_1_calls.append(request.method)

            if request.method == "GET":
                status = HTTPStatus.OK if "G1" in node_1_groups else HTTPStatus.NOT_FOUND
                return httpx.Response(status, request=request)

            if request.method == "POST":
                node_1_groups.add("G1")
                return httpx.Response(HTTPStatus.CREATED, request=request)

            if request.method == "DELETE":
                raise httpx.ConnectError("node unavailable during rollback", request=request)

            return httpx.Response(HTTPStatus.METHOD_NOT_ALLOWED, request=request)

        def node_2_handler(request):
            node_2_calls.append(request.method)

            if request.method == "GET":
                status = HTTPStatus.OK if "G1" in node_2_groups else HTTPStatus.NOT_FOUND
                return httpx.Response(status, request=request)

            if request.method == "POST":
                raise httpx.ConnectError("node unavailable during creation", request=request)

            return httpx.Response(HTTPStatus.METHOD_NOT_ALLOWED, request=request)

        with self.make_orchestrator([node_1_handler, node_2_handler], max_retries=0) as orchestrator:
            with patch("app.client.logger.error"):
                with self.assertRaises(GroupCreateRollbackError) as raised:
                    orchestrator.create_group(Group("G1"))

        self.assertEqual(node_1_calls, ["GET", "POST", "DELETE"])
        self.assertEqual(node_2_calls, ["GET", "POST", "GET"])

        self.assertIn("G1", node_1_groups)
        self.assertNotIn("G1", node_2_groups)

        self.assertIn("MANUAL ACTION REQUIRED", str(raised.exception))
        self.assertIn("MAX RETRIES EXCEEDED", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
