import json
from decimal import Decimal


def _jsonable(value):
    return json.loads(json.dumps(value, default=lambda o: str(o) if not isinstance(o, Decimal) else str(o)))


def record(workspace, actor, action, entity, summary, data=None):
    """Write one audit event. ``entity`` is a model instance or (type, id)."""
    from modules.identity.models import AuditEvent

    if isinstance(entity, tuple):
        entity_type, entity_id = entity
    else:
        entity_type, entity_id = entity._meta.model_name, entity.pk
    return AuditEvent.objects.create(
        workspace=workspace,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        summary=summary[:300],
        data=_jsonable(data or {}),
    )


def diff(instance, fields, new_values):
    changes = {}
    for f in fields:
        if f in new_values:
            old = getattr(instance, f)
            new = new_values[f]
            if str(old) != str(new):
                changes[f] = {"from": old, "to": new}
    return changes
