from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_frontend_build_output_path_is_consistent_across_configs():
    vite_config = (REPO_ROOT / 'web-ui/vite.config.ts').read_text(encoding='utf-8')
    dockerfile = (REPO_ROOT / 'Dockerfile').read_text(encoding='utf-8')
    frontend_dockerfile = (REPO_ROOT / 'web-ui/Dockerfile').read_text(encoding='utf-8')
    dockerignore = (REPO_ROOT / '.dockerignore').read_text(encoding='utf-8').splitlines()
    start_script = (REPO_ROOT / 'start.sh').read_text(encoding='utf-8')

    assert "path.resolve(__dirname, '../dist')" in vite_config
    assert 'COPY --from=frontend-builder --chown=app:app /dist /app/dist' in dockerfile
    assert 'COPY --from=builder /dist /usr/share/nginx/html' in frontend_dockerfile
    assert 'dist' in dockerignore or 'dist/' in dockerignore
    assert '[[ -f dist/index.html ]]' in start_script
    assert 'npm run build' in start_script
    assert 'cp -r web-ui/dist ./' not in start_script
