from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_frontend_build_output_path_is_consistent_across_configs():
    vite_config = (REPO_ROOT / 'web-ui/vite.config.ts').read_text()
    dockerfile = (REPO_ROOT / 'Dockerfile').read_text()
    frontend_dockerfile = (REPO_ROOT / 'web-ui/Dockerfile').read_text()
    dockerignore = (REPO_ROOT / '.dockerignore').read_text().splitlines()
    start_script = (REPO_ROOT / 'start.sh').read_text()

    assert "path.resolve(__dirname, '../dist')" in vite_config
    assert 'COPY --from=frontend-builder --chown=app:app /dist /app/dist' in dockerfile
    assert 'COPY --from=builder /dist /usr/share/nginx/html' in frontend_dockerfile
    assert 'dist' in dockerignore or 'dist/' in dockerignore
    assert '[[ -f dist/index.html ]]' in start_script
    assert 'npm run build' in start_script
    assert 'cp -r web-ui/dist ./' not in start_script
