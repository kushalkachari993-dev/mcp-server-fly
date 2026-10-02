import json
import math
import multiprocessing
import os
import threading

from app.tools.json_utils.tool import _load_bounded_json


_QUERY_TIMEOUT = 3
_QUERY_SLOT = threading.BoundedSemaphore(1)
_MAX_OUTPUT = 100000


def _check_tree(value, max_nodes=10000, max_depth=50):
    stack = [(value, 0)]
    count = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > max_nodes or depth > max_depth:
            raise ValueError("JSON or expression exceeds its node or nesting limit")
        if isinstance(node, float) and not math.isfinite(node):
            raise ValueError("Non-finite numbers are not supported")
        if isinstance(node, (dict, list)):
            if len(node) + len(stack) + count > max_nodes:
                raise ValueError("JSON or expression exceeds its node limit")
            children = node.values() if isinstance(node, dict) else node
            stack.extend((child, depth + 1) for child in children)


def _query_worker(sender, value, expression):
    try:
        if os.name == "posix":
            import resource

            memory = 128 * 1024 * 1024
            soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            resource.setrlimit(resource.RLIMIT_AS, (memory if soft == resource.RLIM_INFINITY else min(soft, memory), hard))
            resource.setrlimit(resource.RLIMIT_CPU, (2, 2))

        import jmespath

        instance = _load_bounded_json(value)
        _check_tree(instance)
        query = jmespath.compile(expression)
        _check_tree(query.parsed, max_nodes=500, max_depth=50)
        result = query.search(instance)
        _check_tree(result)
        chunks = []
        size = 0
        for chunk in json.JSONEncoder(ensure_ascii=True, allow_nan=False).iterencode(result):
            size += len(chunk)
            if size > _MAX_OUTPUT:
                raise ValueError("Query output exceeds 100000 characters; narrow the expression")
            chunks.append(chunk)
        sender.send({"result": "".join(chunks)})
    except Exception as error:
        sender.send({"error": f"JSON query failed: {str(error)[:300]}"})
    finally:
        sender.close()


def query_json(value, expression):
    if len(value) > 200000:
        raise ValueError("Input must not exceed 200000 characters")
    if not expression.strip() or len(expression) > 1000:
        raise ValueError("expression must be nonempty and at most 1000 characters")
    if not _QUERY_SLOT.acquire(blocking=False):
        raise ValueError("JSON querying is busy; retry shortly")
    receiver = sender = process = None
    try:
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_query_worker, args=(sender, value, expression))
        process.start()
        sender.close()
        if not receiver.poll(_QUERY_TIMEOUT):
            raise ValueError("JSON query exceeded its 3-second limit")
        result = receiver.recv()
        if "error" in result:
            raise ValueError(result["error"])
        return result["result"]
    except EOFError as error:
        raise ValueError("JSON query worker exited without a result (possibly a resource limit)") from error
    finally:
        if sender is not None:
            sender.close()
        if receiver is not None:
            receiver.close()
        if process is not None and process.pid is not None:
            process.join(timeout=0.2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join()
            process.close()
        _QUERY_SLOT.release()
