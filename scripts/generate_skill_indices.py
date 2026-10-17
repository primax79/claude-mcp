#!/usr/bin/env python3
"""generate_skill_indices.py - Generates index.json files for claude-mcp."""
import os
import json
import re
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PLUGIN_SKILL_MAPPINGS = [
    ('plugins/architect-side', 'skills'),
    ('plugins/executor-side', 'skills'),
]

PROFILES = {'deep-reasoning', 'orchestration', 'bulk-execution', 'exploration'}


def validate_skill_requirements():
    ok = True
    for rel_plugin_dir, skills_sub in PLUGIN_SKILL_MAPPINGS:
        plugin_dir = os.path.join(ROOT_DIR, rel_plugin_dir)
        skills_dir = os.path.join(plugin_dir, skills_sub)
        if not os.path.isdir(skills_dir):
            continue
        req_path = os.path.join(plugin_dir, 'skill-requirements.json')
        requirements = {}
        if os.path.isfile(req_path):
            with open(req_path, encoding='utf-8') as f:
                requirements = json.load(f)
        for skill_name in sorted(os.listdir(skills_dir)):
            skill_md = os.path.join(skills_dir, skill_name, 'SKILL.md')
            if not os.path.isfile(skill_md):
                continue
            entry = requirements.get(skill_name)
            if entry is None:
                print(f"[roles] FAIL: '{skill_name}' has no skill-requirements.json entry")
                ok = False
                continue
            if entry.get('profile') not in PROFILES:
                print(f"[roles] FAIL: '{skill_name}' has invalid profile {entry.get('profile')!r}")
                ok = False
    return ok


def parse_frontmatter(content):
    if not content.startswith('---'):
        return None
    try:
        _, fm_text, _ = content.split('---', 2)
        name_m = re.search(r'^name:\s*(.+)$', fm_text, re.MULTILINE)
        desc_m = re.search(r'^description:\s*(.+)$', fm_text, re.MULTILINE)
        return {
            'name': name_m.group(1).strip().strip('"\'') if name_m else '',
            'description': desc_m.group(1).strip().strip('"\'') if desc_m else '',
        }
    except Exception:
        return None


def generate_indices():
    if not validate_skill_requirements():
        sys.exit(1)

    plugins_count = 0
    skills_dir_count = 0
    individual_count = 0

    for rel_plugin_dir, skills_sub in PLUGIN_SKILL_MAPPINGS:
        plugin_dir = os.path.join(ROOT_DIR, rel_plugin_dir)
        skills_dir = os.path.join(plugin_dir, skills_sub)
        if not os.path.isdir(skills_dir):
            continue

        skills_list = []
        for sname in sorted(os.listdir(skills_dir)):
            sdir = os.path.join(skills_dir, sname)
            sm = os.path.join(sdir, 'SKILL.md')
            if not os.path.isfile(sm):
                continue
            meta = parse_frontmatter(open(sm, encoding='utf-8').read())
            if not meta:
                continue
            item = {'name': meta['name'], 'description': meta['description'], 'path': f"skills/{sname}/SKILL.md"}
            skills_list.append(item)
            # Individual skill index
            with open(os.path.join(sdir, 'index.json'), 'w', encoding='utf-8') as f:
                json.dump([item], f, indent=2)
            individual_count += 1

        # Skills dir level
        with open(os.path.join(skills_dir, 'index.json'), 'w', encoding='utf-8') as f:
            json.dump(skills_list, f, indent=2)
        skills_dir_count += 1

        # Plugin level
        with open(os.path.join(plugin_dir, 'index.json'), 'w', encoding='utf-8') as f:
            json.dump(skills_list, f, indent=2)
        plugins_count += 1

    print(f"Generated {plugins_count} plugin-level, {skills_dir_count} skills-dir-level, and {individual_count} individual index.json files!")


if __name__ == '__main__':
    generate_indices()
