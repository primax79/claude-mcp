#!/usr/bin/env python3
"""regenerate_bound_skills.py - regenerates claude-mcp's bound skills from
ai-orchestration's generic templates + claude-mcp's bindings/*.json.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BINDINGS_DIR = REPO_ROOT / 'bindings'
PLUGINS_DIR = REPO_ROOT / 'plugins'
DEFAULT_UPSTREAM = (REPO_ROOT / '..' / 'ai-orchestration').resolve()

TEMPLATE_ALIASES = {
    'orchestration-workflow': ('orchestration-workflow', 'orchestration-methodology'),
    'orchestration-metrics': ('orchestration-metrics', 'delegation-roi-analysis'),
    'conflict-resolver': ('conflict-resolver',),
    'executor-contract': ('executor-contract', 'headless-executor-contract'),
}


def find_ai_orchestration(explicit=None):
    if explicit:
        return pathlib.Path(explicit).resolve()
    env = os.environ.get('AI_ORCHESTRATION_PATH')
    if env:
        return pathlib.Path(env).resolve()
    return DEFAULT_UPSTREAM


def find_template(aae_root, skill_id):
    for candidate in TEMPLATE_ALIASES.get(skill_id, (skill_id,)):
        matches = list(aae_root.glob(f'plugins/*/skills/{candidate}/SKILL.template.md'))
        if matches:
            return matches[0]
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ai-orchestration', dest='ai_orchestration', default=None,
                     help='Path to ai-orchestration checkout')
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()

    aae_root = find_ai_orchestration(args.ai_orchestration)
    generator = aae_root / 'scripts' / 'generate_binding.py'
    if not generator.is_file():
        print(f"[FAIL] generator not found at {generator}", file=sys.stderr)
        sys.exit(2)

    failures = 0
    ran = 0
    for map_path in sorted(BINDINGS_DIR.glob('*.json')):
        skill_id = map_path.stem
        template = find_template(aae_root, skill_id)
        if not template:
            print(f"[FAIL] {map_path.name}: no SKILL.template.md for '{skill_id}'")
            failures += 1
            continue

        binding = json.loads(map_path.read_text())
        concrete_name = binding['name']
        plugin = binding.get('plugin')
        out_path = PLUGINS_DIR / plugin / 'skills' / concrete_name / 'SKILL.md'

        cmd = [sys.executable, str(generator), '--template', str(template),
               '--map', str(map_path), '--out', str(out_path)]
        if args.check:
            cmd.append('--check')

        result = subprocess.run(cmd)
        ran += 1
        if result.returncode != 0:
            failures += 1

    verb = 'Checked' if args.check else 'Regenerated'
    print(f"\n{verb} {ran} bound skill(s), {failures} failure(s).")
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
