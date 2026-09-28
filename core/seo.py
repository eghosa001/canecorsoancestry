import json

from django.core.serializers.json import DjangoJSONEncoder
from django.utils.safestring import mark_safe

_ESCAPE = str.maketrans({"<": r"\u003c", ">": r"\u003e", "&": r"\u0026"})


def json_ld(data):
    raw = json.dumps(data, cls=DjangoJSONEncoder, ensure_ascii=False, separators=(",", ":"))
    return mark_safe(raw.translate(_ESCAPE))
