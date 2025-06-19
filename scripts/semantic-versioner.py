#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： semantic-versioner.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2025/6/18 17:37
    @Desc: 
=================================================
"""
import re
import subprocess
from datetime import datetime
from collections import defaultdict
import argparse
from packaging import version

# 提交类型映射和版本影响
COMMIT_TYPES = {
    'feat': {'title': 'Features', 'impact': 'minor'},
    'fix': {'title': 'Bug Fixes', 'impact': 'patch'},
    'perf': {'title': 'Performance', 'impact': 'patch'},
    'docs': {'title': 'Documentation', 'impact': 'none'},
    'style': {'title': 'Styles', 'impact': 'none'},
    'refactor': {'title': 'Refactoring', 'impact': 'none'},
    'test': {'title': 'Tests', 'impact': 'none'},
    'build': {'title': 'Build', 'impact': 'patch'},
    'ci': {'title': 'CI/CD', 'impact': 'none'},
    'chore': {'title': 'Chores', 'impact': 'none'},
    'revert': {'title': 'Reverts', 'impact': 'patch'},
}

# 版本文件路径
VERSION_FILE = 'VERSION'
CHANGELOG_FILE = 'CHANGELOG.md'


def get_current_version():
    """获取当前版本号"""
    try:
        with open(VERSION_FILE, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        # 默认初始版本
        return '0.1.0'


def save_new_version(new_version):
    """保存新版本号"""
    with open(VERSION_FILE, 'w') as f:
        f.write(new_version)
    print(f"✅ Updated version to {new_version}")


def get_commit_history(since_tag=None):
    """获取指定标记后的提交历史"""
    if since_tag:
        # 获取特定标记后的提交
        cmd = ['git', 'log', f'{since_tag}..HEAD', '--pretty=format:%h|%s|%ad', '--date=short', '--no-merges']
    else:
        # 获取所有提交
        cmd = ['git', 'log', '--pretty=format:%h|%s|%ad', '--date=short', '--no-merges']

    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    commits = []
    for line in result.stdout.strip().split('\n'):
        if line:
            parts = line.split('|', 2)
            if len(parts) == 3:
                commits.append({
                    'hash': parts[0],
                    'message': parts[1],
                    'date': parts[2]
                })
    return commits


def parse_commit_message(message):
    """解析提交消息为约定式提交格式"""
    # 匹配约定式提交: type(scope): description
    pattern = r'^(\w+)(?:\(([\w\s\-]+)\))?!?:\s*(.+)$'
    match = re.match(pattern, message)

    if match:
        commit_type = match.group(1).lower()
        scope = match.group(2)
        description = match.group(3).rstrip('.')

        # 检测重大变更
        breaking_change = '!' in message or 'BREAKING CHANGE:' in message

        return {
            'type': commit_type,
            'scope': scope,
            'description': description,
            'breaking': breaking_change
        }
    return None


def determine_version_bump(commits):
    """根据提交历史确定版本升级级别"""
    bump_level = 'patch'  # 默认补丁版本

    for commit in commits:
        parsed = parse_commit_message(commit['message'])
        if not parsed:
            continue

        # 检测重大变更 - 直接升级主版本
        if parsed['breaking']:
            return 'major'

        # 检查功能提交 - 升级次版本
        if parsed['type'] == 'feat':
            bump_level = 'minor'

    return bump_level


def increment_version(current_version, bump_level):
    """根据升级级别递增版本号"""
    v = version.parse(current_version)

    if bump_level == 'major':
        return f"{v.major + 1}.0.0"
    elif bump_level == 'minor':
        return f"{v.major}.{v.minor + 1}.0"
    elif bump_level == 'patch':
        return f"{v.major}.{v.minor}.{v.micro + 1}"
    else:
        return current_version


def generate_changelog(commits, new_version, current_version=None):
    """生成变更日志内容"""
    release_date = datetime.now().strftime('%Y-%m-%d')
    grouped = defaultdict(list)
    breaking_changes = []

    for commit in commits:
        parsed = parse_commit_message(commit['message'])
        if not parsed:
            continue

        # 处理重大变更
        if parsed['breaking']:
            breaking_desc = commit['message'].split('BREAKING CHANGE:')[-1].strip()
            breaking_changes.append({
                'hash': commit['hash'],
                'description': breaking_desc
            })

        # 添加到分类
        if parsed['type'] in COMMIT_TYPES:
            entry = f"- {parsed['description']} ({commit['hash']})"
            if parsed['scope']:
                entry = f"- **{parsed['scope']}:** {parsed['description']} ({commit['hash']})"
            grouped[parsed['type']].append(entry)

    # 构建变更日志
    changelog = [f"## [{new_version}] - {release_date}", ]

    # 添加版本升级说明
    if current_version:
        changelog.append(f"\n### Version Upgrade: `{current_version}` → `{new_version}`")

    # 添加重大变更
    if breaking_changes:
        changelog.append("\n### ⚠ BREAKING CHANGES")
        for change in breaking_changes:
            changelog.append(f"- {change['description']}")

    # 添加分类提交
    for type_key, type_info in COMMIT_TYPES.items():
        if type_key in grouped and grouped[type_key]:
            changelog.append(f"\n### {type_info['title']}")
            changelog.extend(grouped[type_key])

    return '\n'.join(changelog)


def update_changelog_file(new_content, file_path=CHANGELOG_FILE):
    """更新变更日志文件"""
    try:
        # 读取现有内容
        with open(file_path, 'r') as f:
            existing_content = f.read()

        # 在开头插入新内容
        updated_content = f"{new_content}\n\n{existing_content}"
    except FileNotFoundError:
        # 文件不存在时创建新文件
        updated_content = f"# Changelog\n\n{new_content}"

    # 写入文件
    with open(file_path, 'w') as f:
        f.write(updated_content)

    print(f"✅ Updated {file_path}")


def create_git_tag(new_version):
    """创建Git版本标签"""
    tag_name = f"v{new_version}"
    subprocess.run(['git', 'tag', '-a', tag_name, '-m', f"Version {new_version}"], encoding='utf-8')
    print(f"✅ Created Git tag: {tag_name}")


def main():
    parser = argparse.ArgumentParser(description='Automated Semantic Versioning')
    parser.add_argument('--release', action='store_true', help='Create a new release')
    parser.add_argument('--dry-run', action='store_true', help='Simulate without making changes')
    args = parser.parse_args()

    # 获取当前版本
    current_version = get_current_version()
    print(f"当前版本: {current_version}")

    # 获取自上次发布后的提交
    last_tag = f"v{current_version}" if current_version else None
    commits = get_commit_history(since_tag=last_tag)

    if not commits:
        print("⚠️ 自上次发布以来没有新的提交")
        return

    # 确定版本升级级别
    bump_level = determine_version_bump(commits)
    print(f"版本升级级别: {bump_level}")

    # 计算新版本
    new_version = increment_version(current_version, bump_level)

    if new_version == current_version:
        print("⚠️ 无需更改版本")
        return

    print(f"新版本: {new_version}")

    if args.dry_run:
        print("Dry run complete. No changes made.")
        return

    # 生成变更日志
    changelog_content = generate_changelog(commits, new_version, current_version)

    # 更新文件
    save_new_version(new_version)
    update_changelog_file(changelog_content)

    if args.release:
        # 提交更改并创建标签
        subprocess.run(['git', 'add', VERSION_FILE, CHANGELOG_FILE])
        subprocess.run(['git', 'commit', '-m', f"chore(release): v{new_version}"])
        create_git_tag(new_version)
        print(f"🚀 新版本 {new_version} 已发布!")


if __name__ == "__main__":
    main()
