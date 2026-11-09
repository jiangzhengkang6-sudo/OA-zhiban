"""Collect ERROR-level application events without retaining log content or secrets."""
import logging
from pathlib import Path
from .operations_monitor import atomic_json, read_json, stamp, utcnow


class OperationalErrorHandler(logging.Handler):
    def __init__(self, settings):
        super().__init__(logging.ERROR)
        self.settings = settings
        self.path = Path(settings.ops_state_dir) / 'errors.json'

    def receipt(self):
        if self.path.exists():
            data = read_json(self.path)
            if data['tenant_id'] != self.settings.auth_tenant_id or data['version'] != 1:
                raise ValueError('Invalid log receipt')
            return data
        return dict(version=1, tenant_id=self.settings.auth_tenant_id, started_at=stamp(utcnow()), last_error_at=None)

    def emit(self, record):
        if not (record.name == 'oa-agent' or record.name.startswith('app.')):
            return
        try:
            data = self.receipt()
            data['last_error_at'] = stamp(utcnow())
            atomic_json(self.path, data)
        except Exception:
            pass  # Logging must never disrupt requests or recursively log errors.


def install(settings):
    handler = OperationalErrorHandler(settings)
    try:
        atomic_json(handler.path, handler.receipt())
    except Exception:
        pass
    logging.getLogger().addHandler(handler)
    return handler
