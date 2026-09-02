from __future__ import annotations

import importlib.metadata as metadata
import json
import platform
import re
from pathlib import Path

try:
    from packaging.requirements import Requirement
except ImportError:  # pragma: no cover - packaging is present in build environments
    Requirement = None


_LICENSE_CLASSIFIER_MAP = {
    'License :: OSI Approved :: MIT License': 'MIT',
    'License :: OSI Approved :: Apache Software License': 'Apache-2.0',
    'License :: OSI Approved :: BSD License': 'BSD-3-Clause',
    'License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)': 'MPL-2.0',
    'License :: OSI Approved :: Python Software Foundation License': 'Python-2.0',
}


def normalize(name: str) -> str:
    return re.sub(r'[-_.]+', '-', name).lower()


def _license_expression(meta) -> str:
    expression = (meta.get('License-Expression') or '').strip()
    if expression:
        return expression
    legacy = (meta.get('License') or '').strip()
    if legacy:
        return legacy
    for classifier in meta.get_all('Classifier') or []:
        mapped = _LICENSE_CLASSIFIER_MAP.get(classifier.strip())
        if mapped:
            return mapped
    return 'NOASSERTION'


def _project_url(meta) -> str:
    legacy = (meta.get('Home-page') or '').strip()
    if legacy:
        return legacy
    project_urls = []
    for raw in meta.get_all('Project-URL') or []:
        label, sep, value = raw.partition(',')
        if sep and value.strip():
            project_urls.append((label.strip().casefold(), value.strip()))
    priorities = ('homepage', 'home', 'source', 'source code', 'repository', 'code')
    for desired in priorities:
        for label, value in project_urls:
            if label == desired:
                return value
    return project_urls[0][1] if project_urls else ''


def _license_file_paths(dist) -> list:
    out = []
    for entry in dist.files or []:
        text = str(entry).replace('\\', '/')
        name = Path(text).name.casefold()
        parts = [part.casefold() for part in Path(text).parts]
        in_metadata = any(part.endswith('.dist-info') or part.endswith('.egg-info') for part in parts)
        in_metadata_licenses = any(part == 'licenses' for part in parts)
        looks_like_license = name.startswith(('license', 'copying', 'notice'))
        if looks_like_license and (in_metadata_licenses or in_metadata):
            out.append(entry)
    return sorted(out, key=lambda item: str(item).casefold())


def _read_license_texts(dist) -> list[dict]:
    texts = []
    seen_hashless = set()
    for entry in _license_file_paths(dist):
        try:
            path = Path(dist.locate_file(entry))
            raw = path.read_bytes()
        except (OSError, UnicodeError):
            continue
        if not raw or len(raw) > 2 * 1024 * 1024:
            continue
        text = raw.decode('utf-8', errors='replace').replace('\x00', '')
        key = text.strip()
        if not key or key in seen_hashless:
            continue
        seen_hashless.add(key)
        texts.append({'path': str(entry).replace('\\', '/'), 'text': text.rstrip()})
    return texts


def runtime_dependency_closure(root_name='mailarchive'):
    installed = {normalize(dist.metadata['Name']): dist for dist in metadata.distributions() if dist.metadata.get('Name')}
    pending = [normalize(root_name)]
    seen = set()
    components = []
    distributions = {}
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        dist = installed.get(name)
        if dist is None:
            continue
        meta = dist.metadata
        component_name = meta.get('Name')
        component = {
            'type': 'library' if name != normalize(root_name) else 'application',
            'name': component_name,
            'version': dist.version,
            'license': _license_expression(meta),
            'homepage': _project_url(meta),
        }
        components.append(component)
        distributions[normalize(component_name)] = dist
        for raw in dist.requires or []:
            if Requirement is None:
                dep = raw.split(';', 1)[0].split(' ', 1)[0]
                pending.append(normalize(dep))
                continue
            try:
                req = Requirement(raw)
                if req.marker and not req.marker.evaluate():
                    continue
                pending.append(normalize(req.name))
            except Exception:
                continue
    return sorted(components, key=lambda x: normalize(x['name'])), distributions


def build_license_bundle(components: list[dict], distributions: dict) -> str:
    lines = [
        'MailArchive third-party license texts',
        'Generated from the exact installed runtime dependency distributions used for this build.',
        '',
    ]
    missing_text = []
    for item in components:
        name = normalize(item['name'])
        if name == 'mailarchive':
            continue
        lines.extend([
            '=' * 78,
            f"{item['name']} {item['version']}",
            f"Declared license: {item['license']}",
            f"Project: {item['homepage'] or '(see package metadata)'}",
            '=' * 78,
            '',
        ])
        dist = distributions.get(name)
        texts = _read_license_texts(dist) if dist is not None else []
        if not texts:
            missing_text.append(item['name'])
            lines.extend(['[No packaged license text file was discoverable in the installed distribution.]', ''])
            continue
        for record in texts:
            lines.extend([f"--- {record['path']} ---", record['text'], ''])
    if missing_text:
        lines.extend([
            '=' * 78,
            'License text collection warnings',
            '=' * 78,
            'No packaged license text was discoverable for: ' + ', '.join(sorted(missing_text, key=str.casefold)),
            '',
        ])
    return '\n'.join(lines).rstrip() + '\n'


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--licenses', required=True)
    parser.add_argument('--notices', required=True)
    parser.add_argument('--license-texts', required=True)
    parser.add_argument('--application-license-expression', default='')
    args = parser.parse_args(argv)
    components, distributions = runtime_dependency_closure()
    application_license = (args.application_license_expression or '').strip()
    if application_license:
        for item in components:
            if normalize(item['name']) == 'mailarchive':
                item['license'] = application_license
                break
    third_party = [item for item in components if normalize(item['name']) != 'mailarchive']
    unresolved = [item['name'] for item in third_party if item['license'] in {'UNKNOWN', 'NOASSERTION'}]
    if unresolved:
        raise SystemExit('UNRESOLVED_RUNTIME_LICENSE_METADATA:' + ','.join(sorted(unresolved, key=str.casefold)))
    sbom = {
        'bomFormat': 'CycloneDX',
        'specVersion': '1.5',
        'version': 1,
        'metadata': {
            'component': {'type': 'application', 'name': 'MailArchive', 'version': metadata.version('mailarchive'), 'license': application_license or 'NOASSERTION'},
            'properties': [
                {'name': 'runtime.python.version', 'value': platform.python_version()},
                {'name': 'runtime.platform', 'value': platform.platform()},
            ],
        },
        'components': components,
    }
    Path(args.output).write_text(json.dumps(sbom, indent=2, sort_keys=True), encoding='utf-8')
    Path(args.licenses).write_text(json.dumps(third_party, indent=2, sort_keys=True), encoding='utf-8')
    lines = ['MailArchive third-party runtime notices', '']
    for item in third_party:
        lines.extend([
            f"{item['name']} {item['version']}",
            f"License: {item['license']}",
            f"Project: {item['homepage'] or '(see package metadata)'}",
            '',
        ])
    Path(args.notices).write_text('\n'.join(lines), encoding='utf-8')
    Path(args.license_texts).write_text(build_license_bundle(components, distributions), encoding='utf-8')


if __name__ == '__main__':
    main()
