"""Offline deployment checks; these do not claim Windows/Docker execution."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts.backup_database import backup_database
from scripts.check_config import validate_config

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('password', ['', 'admin123', 'password', 'changeme', 'change-me', 'short'])
def test_launch_rejects_missing_or_default_password(password):
    with pytest.raises(ValueError, match='WEB_PASSWORD'):
        validate_config({'WEB_USERNAME': 'local-user', 'WEB_PASSWORD': password})


def test_launch_rejects_blank_user():
    with pytest.raises(ValueError, match='WEB_USERNAME'):
        validate_config({'WEB_USERNAME': ' ', 'WEB_PASSWORD': 'test-only-long-password'})


@pytest.mark.parametrize('port', ['0', '65536', 'eight', '-1'])
def test_launch_rejects_invalid_port(port):
    with pytest.raises(ValueError, match='SERVER_PORT'):
        validate_config({'WEB_USERNAME': 'local-user', 'WEB_PASSWORD': 'test-only-long-password', 'SERVER_PORT': port})


def test_launch_accepts_explicit_config():
    assert validate_config({'WEB_USERNAME': 'local-user', 'WEB_PASSWORD': 'test-only-long-password'}) == 8000


def test_backup_keeps_legacy_tables_and_wal_data(tmp_path):
    source = tmp_path / 'source.sqlite3'
    destination = tmp_path / 'backup.sqlite3'
    with sqlite3.connect(source) as connection:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE legacy (payload TEXT)')
        connection.execute("INSERT INTO legacy VALUES ('keep-me')")
        connection.commit()
        backup_database(source, destination)
    with sqlite3.connect(destination) as backup:
        assert backup.execute('SELECT payload FROM legacy').fetchall() == [('keep-me',)]
        assert backup.execute('PRAGMA integrity_check').fetchone() == ('ok',)


def test_backup_never_overwrites_existing_file(tmp_path):
    source, destination = tmp_path / 'source.sqlite3', tmp_path / 'existing.txt'
    with sqlite3.connect(source) as conn:
        conn.execute('CREATE TABLE untouched (value TEXT)')
    destination.write_text('must survive')
    with pytest.raises(FileExistsError):
        backup_database(source, destination)
    assert destination.read_text(encoding='utf-8') == 'must survive'


def test_backup_failure_removes_only_new_incomplete_backup(tmp_path):
    source, destination = tmp_path / 'not-sqlite', tmp_path / 'failed.sqlite3'
    source.write_text('not a database')
    with pytest.raises(sqlite3.DatabaseError):
        backup_database(source, destination)
    assert source.read_text(encoding='utf-8') == 'not a database'
    assert not destination.exists()


def test_compose_builds_local_fork_and_binds_localhost():
    compose = (ROOT / 'docker-compose.yaml').read_text(encoding='utf-8')
    assert 'context: .' in compose
    assert 'dockerfile: Dockerfile' in compose
    assert '127.0.0.1:${SERVER_PORT:-8000}:8000' in compose
    assert 'usagi-org' not in compose
    assert 'pull_policy: always' not in compose
    assert 'shopee_data:/app/data' in compose


def test_docker_context_excludes_local_secrets():
    patterns = set((ROOT / '.dockerignore').read_text(encoding='utf-8').splitlines())
    for expected in ('.env', '.env.*', '**/*state*.json', '**/*cookie*', 'state', 'data', 'backups', '**/*.key', '**/*.pem'):
        assert expected in patterns
    dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
    assert 'USER app' in dockerfile
    assert 'COPY . ' not in dockerfile
    assert 'spider_v2.py' not in dockerfile
    assert 'playwright install' not in dockerfile
    assert 'usagi-org' not in (ROOT / 'Dockerfile.release').read_text(encoding='utf-8')


def test_docker_keeps_ai_policy_but_excludes_browser_artifacts():
    lines = (ROOT / '.dockerignore').read_text(encoding='utf-8').splitlines()
    assert lines.index('!src/services/ai_token_policy.py') > lines.index('**/*token*')
    assert 'browser-request*.json' in lines and 'browser-results*.json' in lines
    requirements = (ROOT / 'requirements-runtime.txt').read_text(encoding='utf-8')
    assert 'playwright' not in requirements.lower()
    assert 'playwright' in (ROOT / 'requirements-browser.txt').read_text(encoding='utf-8').lower()


def test_windows_launcher_uses_venv_without_policy_changes():
    raw = (ROOT / 'start.ps1').read_bytes()
    assert raw.startswith(b'\xef\xbb\xbf')  # Windows PowerShell 5.1 understands the Chinese text.
    script = raw.decode('utf-8-sig')
    assert 'param([switch]$CheckOnly, [switch]$DoubleClick, [switch]$CollectBrowser)' in script
    assert '.venv\\Scripts\\python.exe' in script
    assert 'npm.cmd' in script
    assert 'scripts\\windows_launch.py' in script
    helper = (ROOT / 'scripts/windows_launch.py').read_text(encoding='utf-8')
    assert '"--host", "127.0.0.1"' in helper
    assert 'Set-ExecutionPolicy' not in script
    assert 'Bypass' not in script


def test_environment_example_contains_no_default_secret():
    entries = {}
    for line in (ROOT / '.env.example').read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            entries[key] = value
    for key in ('WEB_USERNAME', 'WEB_PASSWORD', 'OPENAI_API_KEY', 'DISCORD_WEBHOOK_URL'):
        assert entries[key] == ''


@pytest.mark.skipif(__import__('os').name != 'posix', reason='Bash launcher is tested on POSIX only')
@pytest.mark.parametrize('scenario', ['ready', 'missing_env', 'missing_venv', 'bad_password', 'missing_frontend', 'extra_argument'])
def test_bash_check_only_without_starting_server(tmp_path, scenario):
    import os
    import shutil
    import subprocess
    import sys

    if not shutil.which('node') or not shutil.which('npm'):
        pytest.skip('Node/npm prerequisites are unavailable')
    shutil.copy(ROOT / 'start.sh', tmp_path / 'start.sh')
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    shutil.copy(ROOT / 'scripts/check_config.py', scripts / 'check_config.py')
    if scenario != 'missing_env':
        password = 'short' if scenario == 'bad_password' else 'test-only-long-password'
        (tmp_path / '.env').write_text(f'WEB_USERNAME=test\nWEB_PASSWORD={password}\n')
    if scenario != 'missing_venv':
        binary = tmp_path / '.venv/bin'
        binary.mkdir(parents=True)
        (binary / 'python').symlink_to(sys.executable)
    if scenario != 'missing_frontend':
        (tmp_path / 'dist').mkdir()
        (tmp_path / 'dist/index.html').write_text('not a real frontend')
    before = {str(path.relative_to(tmp_path)) for path in tmp_path.rglob('*')}
    args = ['bash', str(tmp_path / 'start.sh'), '--check-only']
    if scenario == 'extra_argument':
        args.append('not-allowed')
    environment = {key: value for key, value in os.environ.items()
                   if key not in {'WEB_USERNAME', 'WEB_PASSWORD', 'SERVER_PORT'}}
    result = subprocess.run(args, text=True, capture_output=True, timeout=15, env=environment)
    assert (result.returncode == 0) == (scenario == 'ready'), result.stdout + result.stderr
    after = {str(path.relative_to(tmp_path)) for path in tmp_path.rglob('*')}
    assert after == before, 'Check-only must not create runtime files or install dependencies'
    assert 'test-only-long-password' not in result.stdout + result.stderr


def test_release_dockerfile_does_not_drift_from_local_build():
    assert (ROOT / 'Dockerfile.release').read_text(encoding='utf-8') == (ROOT / 'Dockerfile').read_text(encoding='utf-8')
