from http import HTTPStatus


class NodeError(Exception):
    """base exception class for all related exception to nodes"""
    pass


class NodeRequestError(NodeError):
    """connection to specific node cannot be established for any reason that I don't care"""
    pass


class NodeHTTPStatusError(NodeError):
    """Node returned an unsuccessful HTTP response."""

    def __init__(self, status_code: int, message: str = ""):
        self.status_code = status_code
        super().__init__(message or f"Node returned HTTP {status_code}")


class NodeGroupNotFoundError(NodeHTTPStatusError):
    def __init__(self):
        super().__init__(status_code=HTTPStatus.NOT_FOUND)


class NodeGroupPerhapsAlreadyExistsError(NodeHTTPStatusError):
    def __init__(self):
        super().__init__(status_code=HTTPStatus.BAD_REQUEST)


class GroupCreateError(Exception):
    """the group create scenario was failed"""
    pass


class GroupDeleteError(Exception):
    """the group delete scenario was failed"""
    pass


class GroupCreateRollbackError(Exception):
    """the group create rollback scenario was failed"""
    pass


class GroupDeleteRollbackError(Exception):
    """the group delete rollback scenario was failed"""
    pass


class UnknownNodeStateError(Exception):
    """the state of node based-on the Group is Unknown"""
    pass


class NotAcceptableNodeStateError(Exception):
    """the state of node based-on the Group is not what I want"""
    pass
