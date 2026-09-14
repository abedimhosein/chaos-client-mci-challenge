import logging
import time
from http import HTTPStatus
from typing import List

import httpx

from .constants import GroupState
from .exceptions import (
    GroupCreateRollbackError,
    GroupDeleteRollbackError,
    NodeConnectionError,
    NodeGroupPerhapsAlreadyExistsError,
    NodeGroupNotFoundError,
    NodeHTTPStatusError,
    NodeRequestError,
    NotAcceptableNodeStateError,
    UnknownNodeStateError,
    GroupDeleteError,
    GroupCreateError,
)
from .models import Group, Node

logger = logging.getLogger(__name__)


class NodeAdapter:
    def __init__(self, node: Node, timeout: float):
        self.node: Node = node
        self.client = httpx.Client(base_url=self.node.base_url, timeout=timeout)

    def _request(self, method, url, **kwargs):
        try:
            response = self.client.request(method, url, **kwargs)
        except httpx.RequestError as exc:
            raise NodeRequestError() from exc

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise NodeHTTPStatusError(status_code=response.status_code) from exc

        return response

    def create_group(self, group: Group):
        """
        if creation was successful, returns None, if failed raise an exception
        :param group:
        :return:
        :raise: NodeRequestError, NodeHTTPStatusError, NodeGroupAlreadyExistsError
        """
        try:
            self._request(
                method='POST',
                url="/v1/group/",
                json={"groupId": group.group_id}
            )
        except NodeHTTPStatusError as exc:
            if exc.status_code == HTTPStatus.BAD_REQUEST:
                raise NodeGroupPerhapsAlreadyExistsError() from exc
            raise

    def delete_group(self, group: Group):
        """
        if deletion was successful, returns None, if failed rais an exception
        :param group:
        :return:
        :raise: NodeRequestError, NodeHTTPStatusError
        """
        try:
            self._request(
                method="DELETE",
                url="/v1/group/",
                json={"groupId": group.group_id}
            )
        except NodeHTTPStatusError as exc:
            if exc.status_code == HTTPStatus.NOT_FOUND:
                raise NodeGroupNotFoundError() from exc
            raise

    def get_group(self, group: Group):
        """
        if getting was successful, returns None, if failed raise an exception
        :param group:
        :return:
        """
        try:
            self._request(
                method='GET',
                url=f"/v1/group/{group.group_id}/"
            )
        except NodeHTTPStatusError as exc:
            if exc.status_code == HTTPStatus.NOT_FOUND:
                raise NodeGroupNotFoundError() from exc
            raise

    def close(self):
        self.client.close()


class OrchestratorConfig:
    def __init__(self, max_retries: int, timeout: float, backoff: float):
        self.max_retries: int = max_retries
        self.timeout: float = timeout
        self.backoff: float = backoff
        self.hard_consistency: bool = False


class Orchestrator:
    def __init__(self, nodes: List[Node], config: OrchestratorConfig):
        if not nodes:
            raise ValueError("nodes cannot be empty")

        self.config = config
        self.node_adapters = [NodeAdapter(node, self.config.timeout) for node in nodes]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        for adapter in self.node_adapters:
            adapter.close()

    def create_group(self, group: Group):
        logger.info(f"group-creation: starting on {group}.")

        candidates = self._prepare_candidates(group, GroupState.NOT_FOUND)
        if not candidates:
            raise GroupCreateError(f"group-creation: All nodes already have the {group}.")

        successful: List[NodeAdapter] = list()
        uncertainties: List[NodeAdapter] = list()
        root_cause: NodeConnectionError | None = None

        for adapter in candidates:
            try:
                self._create_group_on_node(group, adapter)
            except NodeConnectionError as exc:
                root_cause = exc
                uncertainties.append(adapter)
                break
            else:
                successful.append(adapter)
                logger.info(f"group-creation: SUCCESS {group} on {adapter.node}.")

        if uncertainties:
            logger.error(f"group-creation: FAILED {group} on {uncertainties[0].node}.", exc_info=root_cause)

            try:
                self.rollback_create_group(successful, uncertainties, group)
            except GroupCreateRollbackError as rollback_cause:
                raise GroupCreateRollbackError(
                    f"rolling-back group-creation: FAILED {group}, MANUAL ACTION REQUIRED!:"
                    f"original error: {root_cause}; rollback error: {rollback_cause}"
                ) from rollback_cause
            else:
                raise GroupCreateError(
                    f"group-creation: FAILED {group} on {uncertainties[0].node}, rolling-back group-creation: SUCCESS"
                ) from root_cause
        else:
            logger.info(f"group-creation: SUCCESS {group}.")

    def rollback_create_group(self, rollback_candidates: List[NodeAdapter], uncertainties: List[NodeAdapter], group: Group, tries: int = 0):
        if not self._prepare_retry(tries):
            raise GroupCreateRollbackError("MAX RETRIES EXCEEDED.")

        # --------------- Determining the status of the uncertainties
        for adapter in uncertainties:
            group_state = self._get_group_on_node(group, adapter)

            if group_state == GroupState.UNKNOWN:
                raise GroupCreateRollbackError(f"state of {adapter.node} is UNKNOWN.")

            if group_state == GroupState.FOUND:
                rollback_candidates.append(adapter)

        # --------------- rolling back
        pending = list()
        for adapter in rollback_candidates:
            try:
                self._delete_group_on_node(group, adapter)
            except NodeConnectionError:
                pending.append(adapter)

        if pending:
            self.rollback_create_group(
                rollback_candidates=[],
                uncertainties=pending,
                group=group,
                tries=tries + 1
            )
        else:
            logger.info(f"rolling-back group-creation: {group} SUCCESS.")

    def delete_group(self, group: Group):
        logger.info(f"group-deletion: starting on {group}.")

        candidates = self._prepare_candidates(group, GroupState.FOUND)
        if not candidates:
            raise GroupDeleteError(f"group-deletion: None of the nodes have the group.")

        successful: List[NodeAdapter] = list()
        uncertainties: List[NodeAdapter] = list()
        root_cause: NodeConnectionError | None = None

        for adapter in candidates:
            try:
                self._delete_group_on_node(group, adapter)
            except NodeConnectionError as exc:
                root_cause = exc
                uncertainties.append(adapter)
                break
            else:
                successful.append(adapter)
                logger.info(f"group-deletion {group} SUCCESS on {adapter.node}.")

        if uncertainties:
            logger.error(f"group-deletion FAILED: {group} on {uncertainties[0].node}.", exc_info=root_cause)

            try:
                self.rollback_delete_group(successful, uncertainties, group)
            except GroupDeleteRollbackError as rollback_cause:
                raise GroupDeleteRollbackError(
                    f"rolling-back group-deletion: FAILED {group}, MANUAL ACTION REQUIRED!:"
                    f"original error: {root_cause}; rollback error: {rollback_cause}"
                ) from rollback_cause
            else:
                raise GroupDeleteError(
                    f"group-deletion: FAILED {group} on {uncertainties[0].node}, rolling-back group-deletion: SUCCESS"
                ) from root_cause
        else:
            logger.info(f"group-deletion: SUCCESS {group}.")

    def rollback_delete_group(self, rollback_candidates: List[NodeAdapter], uncertainties: List[NodeAdapter], group: Group, tries: int = 0):
        if not self._prepare_retry(tries):
            raise GroupDeleteRollbackError("MAX RETRIES EXCEEDED.")

        # --------------- Determining the status of the uncertainties
        for adapter in uncertainties:
            group_state = self._get_group_on_node(group, adapter)
            if group_state == GroupState.UNKNOWN:
                raise GroupDeleteRollbackError(f"state of {adapter.node} is UNKNOWN.")

            if group_state == GroupState.NOT_FOUND:
                rollback_candidates.append(adapter)

        pending = list()
        for adapter in rollback_candidates:
            try:
                self._create_group_on_node(group, adapter)
            except NodeConnectionError:
                pending.append(adapter)

        if pending:
            self.rollback_delete_group(
                rollback_candidates=[],
                uncertainties=pending,
                group=group,
                tries=tries + 1
            )
        else:
            logger.info(f"rolling-back group-deletion: {group} SUCCESS.")

    def _prepare_retry(self, tries: int) -> bool:
        if tries > self.config.max_retries:
            return False

        if tries == 0:
            return True

        # exponential backoff
        time.sleep(self.config.backoff * (2 ** (tries - 1)))
        return True

    def _prepare_candidates(self, group: Group, prefer_state: GroupState) -> List[NodeAdapter]:
        logger.info(f"prepare-candidates: starting on {group}.")

        candidates: List[NodeAdapter] = list()

        for adapter in self.node_adapters:
            state = self._get_group_on_node(group, adapter)

            if state == GroupState.UNKNOWN:
                raise UnknownNodeStateError(f"prepare-candidates: state of node={adapter.node} is UNKNOWN for {group}.")

            if self.config.hard_consistency and state != prefer_state:
                raise NotAcceptableNodeStateError(f"prepare-candidates: state of node={adapter.node} is not {prefer_state} for {group} (HARD-CONSISTENCY).")

            if state == prefer_state:
                candidates.append(adapter)

        return candidates

    def _create_group_on_node(self, group: Group, adapter: NodeAdapter):
        tries: int = 0
        root_cause: NodeConnectionError | None = None

        while tries < self.config.max_retries:
            try:
                adapter.create_group(group)
            except NodeConnectionError as exc:
                root_cause = exc
                time.sleep(self._get_exponential_backoff(tries))
            else:
                return

            tries += 1

        raise root_cause

    def _delete_group_on_node(self, group: Group, adapter: NodeAdapter):
        tries: int = 0
        root_cause: NodeConnectionError | None = None

        while tries < self.config.max_retries:
            try:
                adapter.delete_group(group)
            except NodeConnectionError as exc:
                root_cause = exc
                time.sleep(self._get_exponential_backoff(tries))
            else:
                return

            tries += 1

        raise root_cause

    def _get_group_on_node(self, group: Group, adapter: NodeAdapter) -> GroupState:
        tries: int = 0

        while tries < self.config.max_retries:
            try:
                adapter.get_group(group)
            except NodeGroupNotFoundError:
                return GroupState.NOT_FOUND
            except NodeConnectionError:
                time.sleep(self._get_exponential_backoff(tries))
            else:
                return GroupState.FOUND

            tries += 1

        return GroupState.UNKNOWN

    def _get_exponential_backoff(self, tries):
        return self.config.backoff * (2 ** tries)
