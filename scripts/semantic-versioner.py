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
import os
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

# 预发布标签配置
PRE_RELEASE_TAGS = {
    'develop': 'dev',  # 开发分支使用 dev 标签
    'test': 'alpha',  # 测试分支使用 alpha 标签
    'beta': 'beta',  # 预发布分支使用 beta 标签
}

# 默认预发布配置
DEFAULT_CONFIG = {
    "branches": {
        "develop": {
            "pre_release": "dev",
            "build_metadata": "sha.{commit_sha}",
            "auto_increment": True
        },
        "test": {
            "pre_release": "alpha",
            "build_metadata": "build.{build_number}",
            "auto_increment": True
        },
        "beta": {
            "pre_release": "beta",
            "build_metadata": "build.{build_number}",
            "auto_increment": True
        },
        "main": {
            "pre_release": None,
            "build_metadata": None,
            "auto_increment": False
        }
    }
}


def get_current_branch():
    """获取当前分支名称"""
    result = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                            capture_output=True, text=True, encoding='utf-8')
    return result.stdout.strip()


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
    print(f"✅ 版本更新到 {new_version}")


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


def get_build_metadata(config, branch_config):
    """获取构建元数据"""
    if not branch_config.get('build_metadata'):
        return ""

    build_meta = branch_config['build_metadata']

    # 替换占位符
    if '{commit_sha}' in build_meta:
        result = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'],
                                capture_output=True, text=True)
        commit_sha = result.stdout.strip()
        build_meta = build_meta.replace('{commit_sha}', commit_sha)

    if '{build_number}' in build_meta:
        build_number = os.environ.get('GITHUB_RUN_NUMBER', '1')
        build_meta = build_meta.replace('{build_number}', build_number)

    if '{timestamp}' in build_meta:
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        build_meta = build_meta.replace('{timestamp}', timestamp)

    return f"+{build_meta}"


def increment_version(current_version, bump_level, branch):
    """根据升级级别递增版本号，支持预发布版本"""
    branch_config = DEFAULT_CONFIG['branches'].get(branch, {})
    pre_release = branch_config.get('pre_release')
    build_meta = get_build_metadata(DEFAULT_CONFIG, branch_config)
    auto_increment = branch_config.get('auto_increment', False)

    # 分离预发布标签和构建元数据
    base_version = current_version
    pre_tag = None
    pre_counter = None

    # 处理预发布版本
    if '-' in base_version:
        base_version, pre_tag_part = base_version.split('-', 1)
        if '.' in pre_tag_part:
            pre_tag, pre_counter = pre_tag_part.split('.', 1)
        else:
            pre_tag = pre_tag_part
            pre_counter = "0"

    # 解析基础版本
    v = version.parse(base_version)

    # 计算新的基础版本
    if bump_level == 'major':
        new_base = f"{v.major + 1}.0.0"
    elif bump_level == 'minor':
        new_base = f"{v.major}.{v.minor + 1}.0"
    elif bump_level == 'patch':
        new_base = f"{v.major}.{v.minor}.{v.micro + 1}"
    else:
        new_base = base_version

    # 处理预发布版本
    if pre_release:
        # 如果是开发分支且自动递增
        if auto_increment and pre_tag == pre_release and pre_counter:
            try:
                new_counter = int(pre_counter) + 1
            except ValueError:
                new_counter = 1
            return f"{new_base}-{pre_release}.{new_counter}{build_meta}"
        else:
            return f"{new_base}-{pre_release}.1{build_meta}"
    else:
        # 正式版本
        return f"{new_base}{build_meta if build_meta else ''}"


def generate_changelog(commits, new_version, current_version=None, is_pre_release=False):
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
    changelog = []

    if is_pre_release:
        changelog.append(f"## [{new_version}] - {release_date} (Pre-release)")
    else:
        changelog.append(f"## [{new_version}] - {release_date}")

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
        with open(file_path, 'r', encoding='utf-8') as f:
            existing_content = f.read()

        # 确保内容以# Changelog开头
        if existing_content.startswith("# Changelog"):
            # 如果已有标题，保留标题并在其后插入新内容
            # 分割标题和内容部分
            header_end = existing_content.find("\n\n")
            if header_end != -1:
                header = existing_content[:header_end].strip()
                rest_content = existing_content[header_end:].lstrip()
            else:
                header = "# Changelog"
                rest_content = existing_content

            # 构建新内容：标题 + 新变更日志 + 旧内容
            updated_content = f"{header}\n\n{new_content}\n\n{rest_content}"
        else:
            # 如果开头不是# Changelog，则添加标题
            updated_content = f"# Changelog\n\n{new_content}\n\n{existing_content}"
    except FileNotFoundError:
        # 文件不存在时创建新文件
        updated_content = f"# Changelog\n\n{new_content}"

    # 写入文件
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(updated_content)

    print(f"✅ 已更新 {file_path}")


def create_git_tag(new_version, is_pre_release=False):
    """创建Git版本标签"""
    tag_name = f"v{new_version}"
    tag_message = f"Version {new_version}"
    if is_pre_release:
        tag_message += " (Pre-release)"
    subprocess.run(['git', 'tag', '-a', tag_name, '-m', tag_message], encoding='utf-8')

    print(f"✅ 已创建 Git tag: {tag_name}")


def create_github_release(version, is_pre_release=False):
    """创建GitHub发布（需要GH CLI）"""
    pre_release_flag = "--prerelease" if is_pre_release else ""
    subprocess.run(f'gh release create v{version} {pre_release_flag} -t "Release v{version}"',
                   shell=True)
    print(f"✅ Created GitHub release: v{version}")


def main():
    parser = argparse.ArgumentParser(description='Automated Semantic Versioning')
    parser.add_argument('--release', action='store_true', help='Create a new release')
    parser.add_argument('--dry-run', action='store_true', help='Simulate without making changes')
    parser.add_argument('--github-release', action='store_true', help='Create GitHub release')
    args = parser.parse_args()

    # 获取当前分支
    current_branch = get_current_branch()
    print(f"当前分支: {current_branch}")

    is_pre_release = DEFAULT_CONFIG.get('branches').get(current_branch).get('pre_release') is not None

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
    new_version = increment_version(current_version, bump_level, current_branch)

    if new_version == current_version:
        print("⚠️ 无需更改版本")
        return

    print(f"新版本: {new_version}")

    if args.dry_run:
        print("Dry run complete. No changes made.")
        return

    # 生成变更日志
    changelog_content = generate_changelog(
        commits,
        new_version,
        current_version,
        is_pre_release=is_pre_release)

    # 更新文件
    save_new_version(new_version)
    update_changelog_file(changelog_content)

    if args.release:
        # 提交更改并创建标签
        subprocess.run(['git', 'add', VERSION_FILE, CHANGELOG_FILE], encoding='utf-8')
        commit_msg = f"chore(release): v{new_version}"
        if is_pre_release:
            commit_msg += f" [Pre-release: {DEFAULT_CONFIG.get('branches')
            .get(current_branch).get('pre_release')}]"
        subprocess.run(['git', 'commit', '-m', commit_msg], encoding='utf-8')
        create_git_tag(new_version, is_pre_release=is_pre_release)

        if args.github_release:
            create_github_release(new_version, is_pre_release=is_pre_release)

        print(f"🚀 新版本 {new_version} 已发布!")


if __name__ == "__main__":
    # python .\scripts\semantic-versioner.py --release
    main()
