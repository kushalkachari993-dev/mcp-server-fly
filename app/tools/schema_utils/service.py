import multiprocessing

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.validators import validator_for
from referencing import Registry
from referencing.exceptions import NoSuchResource


_VALIDATION_TIMEOUT = 3
_MAX_ERRORS = 50


def _deny_remote_reference(uri):
    raise NoSuchResource(ref=uri)


def _pointer(parts):
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _make_validator(schema):
    validator_class = validator_for(schema, default=None)
    if validator_class is None:
        if isinstance(schema, dict) and "$schema" in schema:
            raise ValueError("Unsupported JSON Schema draft")
        validator_class = Draft202012Validator
    validator_class.check_schema(schema)
    return validator_class(schema, registry=Registry(retrieve=_deny_remote_reference), format_checker=FormatChecker())


def _validate_worker(sender, instance, schema):
    try:
        validator = _make_validator(schema)
        errors = []
        truncated = False
        for error in validator.iter_errors(instance):
            if len(errors) == _MAX_ERRORS:
                truncated = True
                break
            errors.append({
                "path": _pointer(error.absolute_path),
                "schema_path": _pointer(error.absolute_schema_path),
                "message": error.message[:500],
            })
        sender.send({"valid": not errors, "errors": errors, "truncated": truncated})
    except Exception as error:
        sender.send({"error": f"Schema validation failed: {str(error)[:1000]}"})
    finally:
        sender.close()


def validate_schema(instance, schema):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_validate_worker, args=(sender, instance, schema))
    try:
        process.start()
        sender.close()
        if not receiver.poll(_VALIDATION_TIMEOUT):
            raise ValueError("Schema validation exceeded its 3-second limit")
        result = receiver.recv()
        if "error" in result:
            raise ValueError(result["error"])
        return result
    except EOFError as error:
        raise ValueError("Schema validation worker exited without a result") from error
    finally:
        sender.close()
        receiver.close()
        if process.pid is not None:
            process.join(timeout=0.2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join()
            process.close()
