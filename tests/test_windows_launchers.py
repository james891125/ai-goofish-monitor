"""Offline launcher tests, with real CMD/Windows PowerShell cases on Windows.

No Shopee navigation, desktop automation, execution-policy changes or live login.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from unittest.mock import Mock

import pytest

from scripts import windows_launch as launch

ROOT = Path(__file__).resolve().parents[1]
WRAPPERS = ('啟動蝦皮監控.cmd', '實驗瀏覽收集.cmd')
WINDOWS = pytest.mark.skipif(os.name != 'nt', reason='Requires actual Windows CMD and PowerShell 5.1')


@contextmanager
def health_server(body, *, status=200, headers=None):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.path, dict(self.headers)))
            self.send_response(status)
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body if isinstance(body, bytes) else json.dumps(body).encode('utf-8'))

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_port, calls
    finally:
        server.shutdown()
        worker.join(timeout=3)
        server.server_close()


@pytest.mark.parametrize('body,status,expected', [
    ({'status': 'healthy', 'application': launch.APPLICATION}, 200, launch.READY),
    ({'status': 'healthy'}, 200, launch.OCCUPIED),
    ({'status': 'healthy', 'application': 'other'}, 200, launch.OCCUPIED),
    ({'status': 'starting', 'application': launch.APPLICATION}, 200, launch.OCCUPIED),
    ({'status': 'healthy', 'application': launch.APPLICATION}, 503, launch.OCCUPIED),
    (b'not JSON', 200, launch.OCCUPIED), (b'x' * 4097, 200, launch.OCCUPIED),
    ([], 200, launch.OCCUPIED),
])
def test_probe_requires_exact_health(body, status, expected):
    with health_server(body, status=status) as (port, calls):
        assert launch.probe(port) == expected
        assert calls[0][0] == '/health'
        assert 'Authorization' not in calls[0][1]
        assert 'Cookie' not in calls[0][1]


def test_probe_never_uses_proxy_or_follows_redirect(monkeypatch):
    with health_server({'status': 'healthy', 'application': launch.APPLICATION}) as (other, other_calls):
        monkeypatch.setenv('HTTP_PROXY', f'http://127.0.0.1:{other}')
        monkeypatch.setenv('http_proxy', f'http://127.0.0.1:{other}')
        monkeypatch.setenv('NO_PROXY', '')
        with health_server({}, status=302, headers={'Location': f'http://127.0.0.1:{other}/health'}) as (port, _):
            assert launch.probe(port) == launch.OCCUPIED
        assert other_calls == []


def test_probe_free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    assert launch.probe(port) == launch.FREE


@pytest.mark.parametrize('line,expected', [
    ('SERVER_PORT=8123', 8123), ('SERVER_PORT="8123" # local', 8123),
    ("export SERVER_PORT='8123'", 8123), ('SERVER_PORT=\n', 8000),
    ('SERVER_PORT=8123\nSERVER_PORT=8124', 8124), ('# SERVER_PORT=99', 9000),
])
def test_port_reader_matches_ordinary_dotenv(tmp_path, monkeypatch, line, expected):
    monkeypatch.setenv('SERVER_PORT', '9000')
    (tmp_path / '.env').write_text('WEB_PASSWORD=do-not-display\n' + line, encoding='utf-8-sig')
    assert launch.configured_port(tmp_path) == expected


@pytest.mark.parametrize('value', ['0', '65536', 'abc', '$(whoami)', '8000;echo nope'])
def test_port_reader_fails_closed(tmp_path, value):
    (tmp_path / '.env').write_text(f'SERVER_PORT={value}\n', encoding='utf-8')
    with pytest.raises(ValueError):
        launch.configured_port(tmp_path)


def test_existing_app_opens_once_and_does_not_start(tmp_path, monkeypatch):
    (tmp_path / '.env').write_text('SERVER_PORT=8000\n', encoding='utf-8')
    monkeypatch.setattr(launch, 'probe', lambda port: launch.READY)
    opened = Mock()
    monkeypatch.setattr(launch, 'open_app', opened)
    monkeypatch.setattr(launch.subprocess, 'Popen', Mock(side_effect=AssertionError('must not start')))
    assert launch.existing(tmp_path) == 0
    opened.assert_called_once_with(8000)


class FakeProcess:
    def __init__(self, *, exit_code=None, interrupt=False):
        self.returncode = exit_code
        self.interrupt = interrupt
        self.stopped = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.interrupt and timeout is None:
            raise KeyboardInterrupt
        self.returncode = 0
        return 0

    def terminate(self):
        self.stopped = True
        self.returncode = 0

    def send_signal(self, sig):
        self.terminate()


def test_supervisor_waits_until_ready_and_opens_once(tmp_path, monkeypatch):
    statuses = iter([launch.FREE, launch.OCCUPIED, launch.READY])
    monkeypatch.setattr(launch, 'probe', lambda port: next(statuses))
    monkeypatch.setattr(launch.time, 'sleep', lambda _: None)
    process = FakeProcess()
    popen = Mock(return_value=process)
    opened = Mock()
    monkeypatch.setattr(launch.subprocess, 'Popen', popen)
    monkeypatch.setattr(launch, 'open_app', opened)
    assert launch.supervise(tmp_path, 8123, open_browser=True) == 0
    opened.assert_called_once_with(8123)
    args, kwargs = popen.call_args
    assert args[0] == [sys.executable, '-m', 'uvicorn', 'src.app:app', '--host', '127.0.0.1',
                       '--port', '8123', '--env-file', '.env']
    assert 'shell' not in kwargs and kwargs['cwd'] == tmp_path


@pytest.mark.parametrize('case', ['occupied', 'failed', 'timeout', 'interrupt'])
def test_supervisor_failure_and_cleanup(tmp_path, monkeypatch, case):
    states = iter([launch.OCCUPIED if case == 'occupied' else launch.FREE, launch.READY])
    monkeypatch.setattr(launch, 'probe', lambda port: next(states))
    process = FakeProcess(exit_code=7 if case == 'failed' else None, interrupt=case == 'interrupt')
    popen = Mock(return_value=process)
    opened = Mock()
    monkeypatch.setattr(launch.subprocess, 'Popen', popen)
    monkeypatch.setattr(launch, 'open_app', opened)
    result = launch.supervise(tmp_path, 8000, open_browser=True, timeout=0 if case == 'timeout' else 2)
    if case == 'occupied':
        popen.assert_not_called()
    if case != 'interrupt':
        opened.assert_not_called()
        assert result != 0
    else:
        assert result == 0
    if case in ('timeout', 'interrupt'):
        assert process.stopped


def test_collect_uses_literal_paths_fresh_output_and_no_auto_ack(tmp_path, monkeypatch):
    request = tmp_path / '需求 ! & % request.json'
    request.write_text('{}', encoding='utf-8')
    old = tmp_path / 'browser-results.json'
    old.write_text('keep me', encoding='utf-8')
    monkeypatch.setattr(launch, 'choose_request', lambda _: request)
    call = Mock(return_value=0)
    monkeypatch.setattr(launch.subprocess, 'call', call)
    assert launch.collect(tmp_path) == 0
    arguments = call.call_args.args[0]
    assert arguments[arguments.index('--request') + 1] == str(request)
    output = Path(arguments[arguments.index('--output') + 1])
    assert output.parent == tmp_path and output.name.startswith('browser-results-')
    assert not output.exists() and output != old
    assert old.read_text(encoding='utf-8') == 'keep me'
    assert '--risk-acknowledged' not in arguments
    assert 'shell' not in call.call_args.kwargs


def test_collect_cancel_does_not_run_or_create_files(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, 'choose_request', lambda _: None)
    call = Mock()
    monkeypatch.setattr(launch.subprocess, 'call', call)
    assert launch.collect(tmp_path) == 0
    call.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_filepicker_fallback_treats_input_as_path(tmp_path, monkeypatch):
    request = tmp_path / '中文 ! & input.json'
    request.write_text('{}', encoding='utf-8')
    monkeypatch.setitem(sys.modules, 'tkinter', None)
    monkeypatch.setattr('builtins.input', lambda _: f'"{request}"')
    assert launch.choose_request(tmp_path) == request


def test_wrappers_are_crlf_utf8_and_never_override_policy():
    for name in WRAPPERS:
        raw = (ROOT / name).read_bytes()
        assert b'\r\n' in raw and b'\n' not in raw.replace(b'\r\n', b'')
        text = raw.decode('utf-8')
        assert 'setlocal DisableDelayedExpansion' in text
        assert ' -NoProfile -File "%~dp0start.ps1"' in text
        assert '\npause\r\n' in text
        assert '%*' not in text
        for forbidden in (' -ExecutionPolicy ', '-EncodedCommand', 'Invoke-Expression', 'Set-ExecutionPolicy',
                          'Unblock-File', 'python.exe', 'python3.exe', 'py.exe'):
            assert forbidden.lower() not in text.lower()
    raw = (ROOT / 'start.ps1').read_bytes()
    assert raw.startswith(b'\xef\xbb\xbf')
    text = raw.decode('utf-8-sig')
    assert "$env:PYTHONDONTWRITEBYTECODE = '1'" in text
    assert '[System.IO.File]::Copy' in text and "'.env'), $false)" in text


# Actual Windows process tests. All generated fixtures are local, trusted test
# code, not downloaded scripts. No test changes execution policy or zone marks.
def powershell_path():
    path = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    assert path.is_file(), 'Windows PowerShell 5.1 must be present on Windows CI'
    return str(path)


def windows_env():
    result = {key: value for key, value in os.environ.items()
              if key not in {'WEB_USERNAME', 'WEB_PASSWORD', 'SERVER_PORT'}}
    result.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    return result


@pytest.fixture
def windows_project(tmp_path):
    if os.name != 'nt':
        pytest.skip('Windows only')
    root = tmp_path / '中文 專案 ! & 測試'
    root.mkdir()
    shutil.copy(ROOT / 'start.ps1', root / 'start.ps1')
    for wrapper in WRAPPERS:
        shutil.copy(ROOT / wrapper, root / wrapper)
    (root / 'scripts').mkdir()
    shutil.copy(ROOT / 'scripts/check_config.py', root / 'scripts/check_config.py')
    shutil.copy(ROOT / 'scripts/windows_launch.py', root / 'scripts/windows_launch.py')
    (root / '.env').write_text('WEB_USERNAME=test\nWEB_PASSWORD=secret-test-only-long\nSERVER_PORT=8123\n', encoding='utf-8')
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', '--system-site-packages', str(root / '.venv')],
                   check=True, capture_output=True, timeout=40, env=windows_env())
    (root / 'dist').mkdir()
    (root / 'dist/index.html').write_text('offline fixture', encoding='utf-8')
    return root


@WINDOWS
@pytest.mark.parametrize('scenario', ['ready', 'missing_env', 'missing_venv', 'bad_password', 'missing_frontend', 'extra_argument'])
def test_windows_real_powershell_check_only_is_read_only(windows_project, scenario):
    root = windows_project
    if scenario == 'missing_env':
        (root / '.env').unlink()
    elif scenario == 'missing_venv':
        shutil.rmtree(root / '.venv')
    elif scenario == 'bad_password':
        (root / '.env').write_text('WEB_USERNAME=test\nWEB_PASSWORD=short\n', encoding='utf-8')
    elif scenario == 'missing_frontend':
        (root / 'dist/index.html').unlink()
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    args = [powershell_path(), '-NoProfile', '-File', str(root / 'start.ps1'), '-CheckOnly']
    if scenario == 'extra_argument':
        args.append('-UnexpectedArgument')
    result = subprocess.run(args, text=True, encoding='utf-8', errors='replace', capture_output=True,
                            timeout=40, env=windows_env())
    assert (result.returncode == 0) == (scenario == 'ready'), result.stdout + result.stderr
    after = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert before == after
    assert 'secret-test-only-long' not in result.stdout + result.stderr


@WINDOWS
def test_windows_existing_venv_missing_playwright_prompts_before_install(windows_project):
    root = windows_project
    # Make an isolated venv without optional packages, even when CI has Playwright.
    config = root / '.venv/pyvenv.cfg'
    config.write_text(config.read_text(encoding='utf-8').replace('include-system-site-packages = true',
                                                              'include-system-site-packages = false'), encoding='utf-8')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (root / '.env').write_text(f'WEB_USERNAME=test\nWEB_PASSWORD=secret-test-only-long\nSERVER_PORT={port}\n', encoding='utf-8')
    original = (root / '.env').read_bytes()
    result = subprocess.run([powershell_path(), '-NoProfile', '-File', str(root / 'start.ps1'), '-CollectBrowser'],
                            input='no\n', text=True, encoding='utf-8', errors='replace', capture_output=True,
                            timeout=30, env=windows_env())
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'requirements-browser.txt' in result.stdout
    assert '已取消' in result.stdout
    assert 'NativeCommandError' not in result.stderr
    assert not (root / '.venv/.runtime-install.sha256').exists()
    assert (root / '.env').read_bytes() == original


def prepare_cached_windows_project(root):
    (root / 'requirements-runtime.txt').write_text('# no downloads\n', encoding='utf-8')
    (root / 'pip.py').write_text('raise RuntimeError("Unexpected dependency install")\n', encoding='utf-8')
    web = root / 'web-ui'
    (web / 'src').mkdir(parents=True)
    for path in ('package.json', 'package-lock.json', 'vite.config.ts', 'index.html', 'src/main.ts'):
        (web / path).write_text('{}', encoding='utf-8')
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest().upper()
    (root / '.venv/.runtime-install.sha256').write_text(digest(root / 'requirements-runtime.txt'), encoding='utf-8')
    stamp = ':'.join(digest(web / p) for p in ('package.json', 'package-lock.json', 'src/main.ts', 'index.html', 'vite.config.ts'))
    (root / '.venv/.frontend-build.sha256').write_text(stamp, encoding='utf-8')
    helper = '''import os, sys, time
from pathlib import Path
root = Path(__file__).resolve().parents[1]
with (root / 'helper-calls.txt').open('a', encoding='utf-8') as f:
    f.write(sys.argv[1] + '\\n')
if sys.argv[1] == 'existing':
    raise SystemExit(0 if (root / 'running').exists() else 3)
(root / 'running').write_text('started', encoding='utf-8')
if os.environ.get('LAUNCH_TEST_WAIT'):
    while not (root / 'stop-test').exists():
        time.sleep(0.1)
'''
    (root / 'scripts/windows_launch.py').write_text(helper, encoding='utf-8')


@WINDOWS
def test_windows_real_launcher_preserves_config_and_uses_cached_dependencies(windows_project):
    root = windows_project
    prepare_cached_windows_project(root)
    original = (root / '.env').read_bytes()
    result = subprocess.run([powershell_path(), '-NoProfile', '-File', str(root / 'start.ps1'), '-DoubleClick'],
                            text=True, encoding='utf-8', errors='replace', capture_output=True,
                            timeout=40, env=windows_env())
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / 'helper-calls.txt').read_text(encoding='utf-8').splitlines() == ['existing', 'serve']
    assert (root / '.env').read_bytes() == original


@WINDOWS
@pytest.mark.parametrize('phase', ['serving', 'installing'])
def test_windows_real_mutex_prevents_duplicate_start_and_releases(windows_project, phase):
    root = windows_project
    prepare_cached_windows_project(root)
    env = windows_env()
    env['LAUNCH_TEST_WAIT'] = '1'
    if phase == 'installing':
        (root / '.venv/.runtime-install.sha256').unlink()
        (root / 'pip.py').write_text('import time\nfrom pathlib import Path\nr=Path.cwd()\n(r / \"installing\").write_text(\"yes\", encoding=\"utf-8\")\nwhile not (r / \"stop-test\").exists(): time.sleep(0.1)\n', encoding='utf-8')
    waiting_marker = root / ('running' if phase == 'serving' else 'installing')
    args = [powershell_path(), '-NoProfile', '-File', str(root / 'start.ps1'), '-DoubleClick']
    first = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             encoding='utf-8', errors='replace', env=env)
    try:
        deadline = time.monotonic() + 30
        while not waiting_marker.exists() and first.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        assert waiting_marker.exists(), first.communicate(timeout=5)
        second = subprocess.run(args, text=True, encoding='utf-8', errors='replace', capture_output=True,
                                timeout=20, env=windows_env())
        assert second.returncode == 0, second.stdout + second.stderr
        calls = (root / 'helper-calls.txt').read_text(encoding='utf-8').splitlines()
        assert calls.count('serve') == (1 if phase == 'serving' else 0) and calls.count('existing') == 2
    finally:
        (root / 'stop-test').write_text('stop', encoding='utf-8')
        out, err = first.communicate(timeout=20)
    assert first.returncode == 0, out + err
    (root / 'running').unlink()
    third = subprocess.run(args, text=True, encoding='utf-8', errors='replace', capture_output=True,
                           timeout=30, env=windows_env())
    assert third.returncode == 0, third.stdout + third.stderr
    assert (root / 'helper-calls.txt').read_text(encoding='utf-8').splitlines().count('serve') == 2


@WINDOWS
@pytest.mark.parametrize('wrapper,flag', [(WRAPPERS[0], '-DoubleClick'), (WRAPPERS[1], '-CollectBrowser')])
@pytest.mark.parametrize('result_code', [0, 7])
def test_windows_real_cmd_quotes_paths_and_preserves_failure_without_fallback(tmp_path, wrapper, flag, result_code):
    root = tmp_path / '中文 空白 ! & 入口'
    root.mkdir()
    shutil.copy(ROOT / wrapper, root / wrapper)
    # Compile a tiny, trusted local executable that simulates PS acceptance/denial.
    # CMD actually executes the unmodified wrapper, including pause and policy branch.
    mock_root = tmp_path / 'mock windows'
    executable = mock_root / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    executable.parent.mkdir(parents=True)
    source = tmp_path / 'Stub.cs'
    source.write_text('''using System; using System.IO; using System.Text;
class Stub { static int Main(string[] args) {
 File.AppendAllText(Environment.GetEnvironmentVariable("STUB_LOG"), String.Join("|",args)+"\\n",new UTF8Encoding(false));
 if (Array.IndexOf(args,"-Command") >= 0) return 20;
 return Int32.Parse(Environment.GetEnvironmentVariable("STUB_EXIT"));
} }''', encoding='utf-8')
    compilers = list((Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64').glob('v4*/csc.exe'))
    assert compilers, 'Windows CI needs the .NET Framework C# compiler for the offline wrapper fixture'
    subprocess.run([str(compilers[0]), '/nologo', '/target:exe', f'/out:{executable}', str(source)],
                   check=True, capture_output=True, timeout=30)
    env = windows_env()
    log = tmp_path / 'arguments.log'
    env.update(SystemRoot=str(mock_root), STUB_LOG=str(log), STUB_EXIT=str(result_code))
    result = subprocess.run([os.environ['COMSPEC'], '/d', '/c', str(root / wrapper)], input='\n',
                            text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=30, env=env)
    assert result.returncode == result_code, result.stdout + result.stderr
    calls = log.read_text(encoding='utf-8').splitlines()
    assert calls[0] == f'-NoProfile|-File|{root / "start.ps1"}|{flag}'
    assert len(calls) == (1 if result_code == 0 else 2)
    if result_code:
        assert '-Command' in calls[1] and 'Get-ExecutionPolicy' in calls[1]
        assert 'AllSigned' in result.stdout
        assert 'python' not in '\n'.join(calls).lower()
    assert '工作已結束' in result.stdout


@WINDOWS
def test_windows_first_run_copies_env_once_and_uses_notepad_confirmation(windows_project):
    root = windows_project
    prepare_cached_windows_project(root)
    (root / '.env').unlink()
    example = b'WEB_USERNAME=\r\nWEB_PASSWORD=\r\nSERVER_PORT=8123\r\n'
    (root / '.env.example').write_bytes(example)
    # Permitted local fixture script substitutes only the UI function; no desktop
    # or policy change. Production start.ps1 still runs unmodified under -File.
    bootstrap = root / 'ui-fixture.ps1'
    bootstrap.write_text('''function notepad.exe {
 param([string]$Path)
 [IO.File]::WriteAllBytes((Join-Path $PSScriptRoot 'copied-env.txt'), [IO.File]::ReadAllBytes($Path))
 [IO.File]::WriteAllText($Path, "WEB_USERNAME=test`nWEB_PASSWORD=test-only-long-password`nSERVER_PORT=8123`n", [Text.Encoding]::UTF8)
}
function Read-Host { return '' }
& (Join-Path $PSScriptRoot 'start.ps1') -DoubleClick
''', encoding='utf-8-sig')
    result = subprocess.run([powershell_path(), '-NoProfile', '-File', str(bootstrap)],
                            text=True, encoding='utf-8', errors='replace', capture_output=True,
                            timeout=40, env=windows_env())
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / 'copied-env.txt').read_bytes() == example
    saved = (root / '.env').read_bytes()
    second = subprocess.run([powershell_path(), '-NoProfile', '-File', str(root / 'start.ps1'), '-DoubleClick'],
                            text=True, encoding='utf-8', errors='replace', capture_output=True,
                            timeout=30, env=windows_env())
    assert second.returncode == 0, second.stdout + second.stderr
    assert (root / '.env').read_bytes() == saved
    assert 'test-only-long-password' not in result.stdout + result.stderr


@WINDOWS
def test_windows_ready_collector_can_run_beside_app_without_install(windows_project):
    root = windows_project
    prepare_cached_windows_project(root)
    # A local empty module is sufficient for the dependency-presence probe. The
    # helper is mocked, so this never imports Playwright or opens a browser.
    (root / 'playwright.py').write_text('# offline optional-package fixture\n', encoding='utf-8')
    env = windows_env()
    env['LAUNCH_TEST_WAIT'] = '1'
    args = [powershell_path(), '-NoProfile', '-File', str(root / 'start.ps1')]
    app = subprocess.Popen(args + ['-DoubleClick'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, encoding='utf-8', errors='replace', env=env)
    try:
        deadline = time.monotonic() + 30
        while not (root / 'running').exists() and app.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        assert (root / 'running').exists(), app.communicate(timeout=5)
        result = subprocess.run(args + ['-CollectBrowser'], text=True, encoding='utf-8', errors='replace',
                                capture_output=True, timeout=25, env=windows_env())
        assert result.returncode == 0, result.stdout + result.stderr
        assert app.poll() is None
        assert 'collect' in (root / 'helper-calls.txt').read_text(encoding='utf-8').splitlines()
        assert 'requirements-browser.txt' not in result.stdout
    finally:
        (root / 'stop-test').write_text('stop', encoding='utf-8')
        app.communicate(timeout=20)
