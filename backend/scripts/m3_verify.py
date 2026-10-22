"""Run serial M3 checks with explicit, isolated database and model settings."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
DATABASES = frozenset({'oa_business_m3_test', 'oa_business_m3_preview_test'})
OUTPUT = ROOT / 'data' / 'verification' / 'm3'


def configure(database='oa_business_m3_test'):
    if database not in DATABASES:
        raise RuntimeError('M3 database is outside the approved allowlist')
    from sqlalchemy.engine import make_url
    from app.db.safety import validate_test_targets
    address = make_url(os.environ.get('M3_DATABASE_SERVER_URL', 'postgresql://oa:oa@localhost:5433/postgres'))
    urls = [address.set(drivername=driver, database=database).render_as_string(hide_password=False)
            for driver in ('postgresql+asyncpg', 'postgresql+psycopg', 'postgresql')]
    validate_test_targets('test', True, *urls)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    os.environ.update(dict(zip(('DATABASE_URL', 'DATABASE_SYNC_URL', 'CHECKPOINTER_URL'), urls)))
    os.environ.update({
        'ENVIRONMENT': 'test', 'ALLOW_TEST_DATABASE_RESET': 'true',
        'LLM_PROVIDER': 'mock', 'LLM_FALLBACK_PROVIDER': 'none',
        'EMBEDDING_PROVIDER': 'mock', 'EMBEDDING_DIM': '1536',
        # The default M3 verification suite initializes the graph. Tests that
        # cover the manual AI-disabled path override this value explicitly.
        'OA_PROVIDER': 'mock', 'AUTH_PROVIDER': 'mock', 'AI_ENABLED': 'true',
        'SMTP_ENABLED': 'false', 'SMTP_HOST': '127.0.0.1', 'SMTP_USERNAME': '', 'SMTP_PASSWORD': '',
        'CLAMD_HOST': '', 'MOCK_STATE_FILE': str(OUTPUT / 'mock-state.json'),
        'ATTACHMENT_STORAGE_DIR': str(OUTPUT / 'attachments'),
        'KNOWLEDGE_STORAGE_DIR': str(OUTPUT / 'knowledge'),
        'AUDIT_EXPORT_STORAGE_DIR': str(OUTPUT / 'exports'),
    })
    return address.set(drivername='postgresql', database='postgres'), database


def ensure_database(address, database):
    import psycopg
    from psycopg import sql
    if database not in DATABASES:
        raise RuntimeError('M3 database is outside the approved allowlist')
    with psycopg.connect(address.render_as_string(hide_password=False), autocommit=True) as connection:
        if not connection.execute('SELECT 1 FROM pg_database WHERE datname=%s', (database,)).fetchone():
            connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--log', default='latest-tests.log')
    parser.add_argument('tests', nargs='*')
    args = parser.parse_args()
    address, database = configure()
    ensure_database(address, database)
    print('M3 isolated database validated: ' + database)
    if args.prepare_only:
        return 0
    log = OUTPUT / Path(args.log).name
    with log.open('w', encoding='utf-8') as stream:
        result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '--tb=short',
            *(args.tests or ['tests/migrations/test_builtin_business_migration.py'])],
            cwd=BACKEND, env=os.environ.copy(), stdout=stream, stderr=subprocess.STDOUT)
    print('Tests exited with code ' + str(result.returncode) + '; log: ' + str(log))
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
