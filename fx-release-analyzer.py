#!/usr/bin/env python3
"""
Firefox Release Analyzer

A tool to analyze all work that went into a specific Firefox release,
including commits and bug fixes, then generate a summary using Claude API.
Uses bmo-to-md for rich bug information.
"""

import os
import json
import requests
import subprocess
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import re


@dataclass
class Commit:
    hash: str
    author: str
    date: str
    message: str
    files_changed: List[str]
    insertions: int
    deletions: int
    bug_ids: List[int]


class FirefoxReleaseInfo:
    """Helper to get Firefox release information"""
    
    # Firefox release dates and tag patterns
    RELEASE_PATTERNS = {
        # Major releases follow FIREFOX_XX_0_RELEASE pattern
        'major': r'FIREFOX_(\d+)_0_RELEASE',
        # Point releases follow FIREFOX_XX_Y_RELEASE pattern  
        'point': r'FIREFOX_(\d+)_(\d+)_RELEASE',
        # Beta releases
        'beta': r'FIREFOX_(\d+)_0b(\d+)_RELEASE'
    }
    
    @classmethod
    def get_release_tags(cls, repo_path: str, version: str) -> Tuple[str, str]:
        """Get the start and end tags for a Firefox version"""
        try:
            # Get all tags
            result = subprocess.run(
                ['git', '-C', repo_path, 'tag', '-l', '*FIREFOX*RELEASE*'],
                capture_output=True, text=True, check=True
            )
            tags = result.stdout.strip().split('\n')
            
            # Parse version number - handle point releases like 143.0.1
            version_parts = version.split('.')
            if len(version_parts) >= 3:
                # Point release like 143.0.1
                major = version_parts[0]
                minor = version_parts[1]
                patch = version_parts[2]
                target_tag = f"FIREFOX_{major}_{minor}_{patch}_RELEASE"
                # For point releases, previous is typically the base release (143.0.1 -> 143.0)
                prev_version = f"{major}.{minor}"
            elif len(version_parts) == 2:
                # Major release like 143.0
                major = version_parts[0]
                minor = version_parts[1]
                target_tag = f"FIREFOX_{major}_{minor}_RELEASE"
                if minor == "0":
                    prev_version = f"{int(major)-1}.0"
                else:
                    prev_version = f"{major}.{int(minor)-1}"
            else:
                # Just major version like 143
                major = version
                target_tag = f"FIREFOX_{major}_0_RELEASE"
                prev_version = f"{int(major)-1}.0"
            
            # Find the target tag
            end_tag = None
            for tag in tags:
                if target_tag in tag:
                    end_tag = tag
                    break
            
            if not end_tag:
                raise ValueError(f"Could not find release tag for Firefox {version}")
            
            # Find the previous release tag for comparison
            prev_parts = prev_version.split('.')
            start_tag = None
            
            # Try multiple patterns for the previous release
            prev_patterns = []
            if len(prev_parts) == 2:
                # For 143.0 format, try both FIREFOX_143_0_RELEASE
                prev_patterns.append(f"FIREFOX_{prev_parts[0]}_{prev_parts[1]}_RELEASE")
            elif len(prev_parts) >= 3:
                # For 143.0.0 format
                prev_patterns.append(f"FIREFOX_{prev_parts[0]}_{prev_parts[1]}_{prev_parts[2]}_RELEASE")
                prev_patterns.append(f"FIREFOX_{prev_parts[0]}_{prev_parts[1]}_RELEASE")
            
            # Find the matching tag
            for prev_pattern in prev_patterns:
                for tag in tags:
                    if tag == prev_pattern:  # Exact match
                        start_tag = tag
                        break
                if start_tag:
                    break
            
            if not start_tag:
                # If we can't find previous version, use a reasonable fallback
                print(f"Warning: Could not find previous release tag, using 6 months before {end_tag}")
                return None, end_tag
            
            return start_tag, end_tag
            
        except subprocess.CalledProcessError as e:
            raise ValueError(f"Error accessing git repository: {e}")


class BmoToMdClient:
    """Client that uses the bmo-to-md command-line tool for fetching bug information"""
    
    def __init__(self, bmo_to_md_path: str = "bmo-to-md"):
        self.bmo_to_md_path = bmo_to_md_path
        self._verify_bmo_to_md()
    
    def _verify_bmo_to_md(self):
        """Verify that bmo-to-md is available"""
        try:
            result = subprocess.run([self.bmo_to_md_path, "--help"], 
                                  capture_output=True, text=True, check=False)
            if result.returncode != 0:
                print(f"Warning: {self.bmo_to_md_path} not found or not working")
                print("Please install bmo-to-md: https://github.com/padenot/bmo-to-md")
                print("Or specify the correct path with --bmo-path")
        except FileNotFoundError:
            print(f"Error: {self.bmo_to_md_path} not found in PATH")
            print("Please install bmo-to-md: https://github.com/padenot/bmo-to-md")
            raise
    
    def get_bugs_for_release(self, version: str) -> List[Dict[str, str]]:
        """Fetch bugs that were fixed in a specific Firefox version using Bugzilla search"""
        # Try multiple milestone formats that Firefox uses
        milestone_queries = [
            f'firefox{version}',
            f'Firefox {version}',
            f'{version}',
            f'mozilla{version}'
        ]
        
        all_bug_ids = set()
        
        # First, get bug IDs using direct Bugzilla REST API (lightweight query)
        for milestone in milestone_queries:
            bug_ids = self._search_bugs_by_milestone(milestone)
            all_bug_ids.update(bug_ids)
        
        if not all_bug_ids:
            print(f"No bugs found for Firefox {version} milestone")
            return []
        
        print(f"Found {len(all_bug_ids)} bugs for Firefox {version}, fetching detailed markdown...")
        
        # Now use bmo-to-md to get rich markdown for each bug
        return self.get_bugs_markdown(list(all_bug_ids))
    
    def _search_bugs_by_milestone(self, milestone: str) -> List[int]:
        """Search for bug IDs using Bugzilla REST API"""
        url = "https://bugzilla.mozilla.org/rest/bug"
        params = {
            'target_milestone': milestone,
            'resolution': 'FIXED',
            'limit': 1000,
            'include_fields': 'id'
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return [bug['id'] for bug in data['bugs']]
        except requests.exceptions.RequestException:
            return []
    
    def get_bugs_markdown(self, bug_ids: List[int]) -> List[Dict[str, str]]:
        """Get bug information as markdown using bmo-to-md"""
        if not bug_ids:
            return []
        
        bugs_markdown = []
        
        # Process bugs in batches to avoid command line length limits
        batch_size = 50
        for i in range(0, len(bug_ids), batch_size):
            batch = bug_ids[i:i + batch_size]
            batch_str = ",".join(map(str, batch))
            
            try:
                cmd = [self.bmo_to_md_path, batch_str]
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                
                if result.stdout.strip():
                    # Parse the markdown output - bmo-to-md outputs one bug per "section"
                    markdown_content = result.stdout.strip()
                    
                    # Split by bug boundaries (usually "# Bug XXXXXX" headers)
                    bug_sections = self._split_markdown_by_bugs(markdown_content, batch)
                    
                    for bug_id, content in bug_sections:
                        bugs_markdown.append({
                            'id': bug_id,
                            'markdown': content
                        })
                
            except subprocess.CalledProcessError as e:
                print(f"Warning: bmo-to-md failed for batch {batch}: {e}")
                continue
            except Exception as e:
                print(f"Warning: Error processing batch {batch}: {e}")
                continue
        
        print(f"Successfully fetched markdown for {len(bugs_markdown)} bugs")
        return bugs_markdown
    
    def _split_markdown_by_bugs(self, markdown: str, bug_ids: List[int]) -> List[Tuple[int, str]]:
        """Split markdown output into individual bug sections"""
        # bmo-to-md typically outputs with "# Bug XXXXXX" headers
        sections = []
        current_bug_id = None
        current_content = []
        
        for line in markdown.split('\n'):
            # Look for bug headers
            if line.startswith('# Bug '):
                # Save previous bug if we have one
                if current_bug_id and current_content:
                    sections.append((current_bug_id, '\n'.join(current_content)))
                
                # Extract bug ID from header
                try:
                    bug_id = int(line.split('# Bug ')[1].split()[0])
                    if bug_id in bug_ids:
                        current_bug_id = bug_id
                        current_content = [line]
                    else:
                        current_bug_id = None
                        current_content = []
                except (ValueError, IndexError):
                    current_bug_id = None
                    current_content = []
            elif current_bug_id:
                current_content.append(line)
        
        # Don't forget the last bug
        if current_bug_id and current_content:
            sections.append((current_bug_id, '\n'.join(current_content)))
        
        return sections


class GitAnalyzer:
    """Analyzer for Git commits in a Firefox repository"""
    
    def __init__(self, repo_path: str = "."):
        self.repo_path = repo_path
        self._verify_firefox_repo()
    
    def _verify_firefox_repo(self):
        """Verify this looks like a Firefox repository"""
        try:
            result = subprocess.run(
                ['git', '-C', self.repo_path, 'remote', '-v'],
                capture_output=True, text=True, check=True
            )
            if 'mozilla' not in result.stdout.lower():
                print("Warning: This doesn't appear to be a Mozilla Firefox repository")
        except subprocess.CalledProcessError:
            raise ValueError(f"Not a git repository: {self.repo_path}")
    
    def get_commits_for_release(self, version: str) -> List[Commit]:
        """Get all commits that went into a specific Firefox release"""
        try:
            start_tag, end_tag = FirefoxReleaseInfo.get_release_tags(self.repo_path, version)
            
            if start_tag:
                print(f"Analyzing commits from {start_tag} to {end_tag}")
                cmd = ['git', '-C', self.repo_path, 'log', f'{start_tag}..{end_tag}', 
                       '--format=%H|%an|%ad|%s', '--date=iso', '--numstat']
            else:
                print(f"Analyzing commits up to {end_tag} (last 6 months)")
                cmd = ['git', '-C', self.repo_path, 'log', end_tag, '--since=6 months ago',
                       '--format=%H|%an|%ad|%s', '--date=iso', '--numstat']
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            commits = self._parse_git_log(result.stdout)
            
            print(f"Found {len(commits)} commits for Firefox {version}")
            return commits
            
        except Exception as e:
            print(f"Error getting commits for release: {e}")
            return []
    
    def _parse_git_log(self, output: str) -> List[Commit]:
        """Parse git log output into Commit objects"""
        commits = []
        lines = output.strip().split('\n')
        i = 0
        
        while i < len(lines):
            if '|' in lines[i]:
                # Parse commit info line
                parts = lines[i].split('|', 3)
                if len(parts) >= 4:
                    hash_val = parts[0]
                    author = parts[1]
                    date = parts[2]
                    message = parts[3]
                    
                    # Extract bug IDs from commit message
                    bug_ids = self._extract_bug_ids(message)
                    
                    # Parse file changes
                    i += 1
                    files_changed = []
                    insertions = 0
                    deletions = 0
                    
                    while i < len(lines) and '\t' in lines[i]:
                        parts = lines[i].split('\t')
                        if len(parts) >= 3:
                            try:
                                add = int(parts[0]) if parts[0] != '-' else 0
                                delete = int(parts[1]) if parts[1] != '-' else 0
                                filename = parts[2]
                                
                                insertions += add
                                deletions += delete
                                files_changed.append(filename)
                            except ValueError:
                                pass
                        i += 1
                    
                    commits.append(Commit(
                        hash=hash_val,
                        author=author,
                        date=date,
                        message=message,
                        files_changed=files_changed,
                        insertions=insertions,
                        deletions=deletions,
                        bug_ids=bug_ids
                    ))
                    continue
            i += 1
        
        return commits
    
    def _extract_bug_ids(self, message: str) -> List[int]:
        """Extract bug IDs from commit message"""
        bug_ids = []
        patterns = [
            r'[Bb]ug (\d+)',
            r'#(\d+)',
            r'(\d{6,})'  # 6+ digit numbers that might be bug IDs
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, message)
            for match in matches:
                try:
                    bug_id = int(match)
                    if 100000 <= bug_id <= 9999999:  # Reasonable bug ID range
                        bug_ids.append(bug_id)
                except ValueError:
                    continue
        
        return list(set(bug_ids))  # Remove duplicates


class ClaudeAnalyzer:
    """Analyzer using Claude API for generating release summaries"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.anthropic.com/v1/messages"
        self.headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
    
    def analyze_release(self, version: str, bugs_markdown: List[Dict[str, str]], commits: List[Commit]) -> str:
        """Generate a comprehensive analysis of a Firefox release"""
        
        # Analyze commit patterns
        commit_stats = self._analyze_commit_patterns(commits)
        
        prompt = self._create_release_analysis_prompt(version, bugs_markdown, commits, commit_stats)
        
        data = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 4000,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        
        # Check if prompt is too long and truncate if necessary
        if len(prompt) > 150000:  # Conservative limit to avoid hitting API limits
            print(f"Warning: Prompt is very long ({len(prompt)} chars), truncating...")
            prompt = prompt[:150000] + "\n\n(Note: Analysis truncated due to length limits)"
            data["messages"][0]["content"] = prompt
        
        try:
            response = requests.post(self.base_url, headers=self.headers, json=data)
            response.raise_for_status()
            
            result = response.json()
            return result['content'][0]['text']
            
        except requests.exceptions.RequestException as e:
            error_details = ""
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_json = e.response.json()
                    error_details = f"API Error: {error_json.get('error', {}).get('message', 'Unknown error')}"
                except:
                    error_details = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            
            return f"Error calling Claude API: {e}\n{error_details}"
    
    def _analyze_commit_patterns(self, commits: List[Commit]) -> Dict[str, Any]:
        """Analyze patterns in commits"""
        stats = {
            'total_commits': len(commits),
            'total_files_changed': sum(len(c.files_changed) for c in commits),
            'total_insertions': sum(c.insertions for c in commits),
            'total_deletions': sum(c.deletions for c in commits),
            'contributors': set(c.author for c in commits),
            'file_types': {},
            'components': {}
        }
        
        # Analyze file types and components
        for commit in commits:
            for file_path in commit.files_changed:
                # File type analysis
                if '.' in file_path:
                    ext = file_path.split('.')[-1].lower()
                    stats['file_types'][ext] = stats['file_types'].get(ext, 0) + 1
                
                # Component analysis (rough)
                if '/' in file_path:
                    component = file_path.split('/')[0]
                    stats['components'][component] = stats['components'].get(component, 0) + 1
        
        return stats
    
    def _create_release_analysis_prompt(self, version: str, bugs_markdown: List[Dict[str, str]], 
                                      commits: List[Commit], commit_stats: Dict) -> str:
        """Create a comprehensive prompt for Firefox release analysis"""
        
        prompt = f"""I need you to analyze Firefox {version} release and provide a comprehensive summary of what was included in this release.

## Release Overview
Firefox Version: {version}
Total Commits: {commit_stats['total_commits']}
Total Bug Fixes: {len(bugs_markdown)}
Contributors: {len(commit_stats['contributors'])}
Files Changed: {commit_stats['total_files_changed']}
Code Changes: +{commit_stats['total_insertions']}/-{commit_stats['total_deletions']} lines

## Top Components (by commit activity):
"""
        
        # Add top components from commits
        sorted_components = sorted(commit_stats['components'].items(), 
                                 key=lambda x: x[1], reverse=True)[:10]
        for component, count in sorted_components:
            prompt += f"- {component}: {count} files modified\n"
        
        prompt += f"\n## File Type Distribution:\n"
        sorted_file_types = sorted(commit_stats['file_types'].items(), 
                                 key=lambda x: x[1], reverse=True)[:8]
        for file_type, count in sorted_file_types:
            prompt += f"- .{file_type}: {count} files\n"
        
        prompt += "\n## Significant Commits:\n"
        
        # Add significant commits (large changes or security-related) with links
        significant_commits = sorted(commits, 
                                   key=lambda c: c.insertions + c.deletions, 
                                   reverse=True)[:15]
        
        for commit in significant_commits:
            change_size = commit.insertions + commit.deletions
            # Create link to commit on the official Firefox repository
            commit_url = f"https://github.com/mozilla-firefox/firefox/commit/{commit.hash}"
            prompt += f"- [{commit.hash[:8]}]({commit_url}): {commit.message[:120]}... "
            prompt += f"({change_size} lines changed)\n"
        
        prompt += "\n## Detailed Bug Information (Markdown Format):\n\n"
        
        # Include the rich markdown bug information - limit to most important bugs
        # Sort bugs by some priority heuristic and reduce count to avoid token limits
        important_bugs = self._prioritize_bugs(bugs_markdown)[:15]  # Reduced from 25 to 15
        
        for bug_info in important_bugs:
            # Truncate very long bug descriptions to avoid token limits
            bug_markdown = bug_info['markdown']
            if len(bug_markdown) > 2000:  # Limit individual bug markdown length
                bug_markdown = bug_markdown[:2000] + "\n...(truncated)"
            
            # Add Bugzilla link if not already present in the markdown
            bug_id = bug_info['id']
            if f"https://bugzilla.mozilla.org/show_bug.cgi?id={bug_id}" not in bug_markdown:
                bug_url = f"https://bugzilla.mozilla.org/show_bug.cgi?id={bug_id}"
                bug_markdown = f"**[View on Bugzilla]({bug_url})**\n\n" + bug_markdown
            
            prompt += f"{bug_markdown}\n\n---\n\n"
        
        if len(bugs_markdown) > 15:
            prompt += f"(Note: {len(bugs_markdown) - 15} additional bugs were fixed but not included above due to length constraints)\n\n"
        
        prompt += """
Please provide a comprehensive Firefox release analysis including:

1. **Executive Summary**: What Firefox users can expect from this release - highlight the most impactful changes
2. **Major Features and Improvements**: Key new functionality or enhancements based on the bug fixes and commits
3. **Security and Stability**: Critical bug fixes, security improvements, crash fixes - reference specific bugs where relevant with links
4. **Performance**: Changes that impact browser performance, memory usage, startup time, etc.
5. **Web Platform**: New web standards support, API changes, developer features
6. **User Interface**: UI/UX improvements and changes
7. **Developer Tools**: Updates to Firefox DevTools
8. **Platform Support**: Changes for different operating systems (Windows, macOS, Linux, mobile)
9. **Under the Hood**: Technical improvements, refactoring, code quality improvements
10. **Notable Bug Fixes**: Highlight particularly important or long-standing issues that were resolved

IMPORTANT FORMATTING REQUIREMENTS:
- When referencing bugs, use this format: [Bug 1234567](https://bugzilla.mozilla.org/show_bug.cgi?id=1234567)
- When referencing commits, use this format: [abcd1234](https://github.com/mozilla-firefox/firefox/commit/abcd1234567890...)
- Include clickable links for all bug and commit references
- Use markdown formatting throughout

Focus on translating technical changes into user-facing benefits. Use the detailed bug information provided to give specific examples and context. 

Group related changes together and explain the broader themes or initiatives they represent. If you see patterns suggesting major feature work, security initiatives, or technical improvements, call those out specifically.

Make this analysis valuable for both end users who want to know what's new and developers who need to understand the technical changes. Ensure all bug and commit references are properly linked."""

        return prompt
    
    def _prioritize_bugs(self, bugs_markdown: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Prioritize bugs based on importance heuristics"""
        def bug_priority_score(bug_info):
            markdown = bug_info['markdown'].lower()
            score = 0
            
            # High priority keywords
            if any(word in markdown for word in ['security', 'crash', 'critical', 'regression']):
                score += 10
            if any(word in markdown for word in ['performance', 'memory', 'leak', 'startup']):
                score += 8
            if any(word in markdown for word in ['feature', 'implement', 'support']):
                score += 6
            if any(word in markdown for word in ['ui', 'interface', 'devtools']):
                score += 4
            
            # Severity indicators
            if 'severity: critical' in markdown or 'severity: major' in markdown:
                score += 5
            
            # Length as a proxy for complexity/importance
            score += min(len(markdown) / 1000, 3)  # Cap at 3 points
            
            return score
        
        return sorted(bugs_markdown, key=bug_priority_score, reverse=True)


class FirefoxReleaseAnalyzer:
    """Main analyzer class for Firefox releases"""
    
    def __init__(self, claude_api_key: str, repo_path: str = ".", bmo_to_md_path: str = "bmo-to-md"):
        self.bmo_client = BmoToMdClient(bmo_to_md_path)
        self.git_analyzer = GitAnalyzer(repo_path)
        self.claude_analyzer = ClaudeAnalyzer(claude_api_key)
    
    def analyze_release(self, version: str) -> str:
        """Perform complete analysis of a Firefox release"""
        print(f"Analyzing Firefox {version} release...")
        
        # Get commits for the release
        print("Fetching commits from git repository...")
        commits = self.git_analyzer.get_commits_for_release(version)
        
        # Extract unique bug IDs from commits
        bug_ids_from_commits = set()
        for commit in commits:
            bug_ids_from_commits.update(commit.bug_ids)
        
        # Get bugs using bmo-to-md (both milestone-based and commit-referenced)
        print("Fetching bugs using bmo-to-md...")
        milestone_bugs = self.bmo_client.get_bugs_for_release(version)
        
        if bug_ids_from_commits:
            print(f"Fetching {len(bug_ids_from_commits)} additional bugs referenced in commits...")
            commit_bugs = self.bmo_client.get_bugs_markdown(list(bug_ids_from_commits))
            
            # Combine and deduplicate bugs
            all_bugs = {bug['id']: bug for bug in milestone_bugs}
            for bug in commit_bugs:
                all_bugs[bug['id']] = bug
            
            bugs_markdown = list(all_bugs.values())
        else:
            bugs_markdown = milestone_bugs
        
        print(f"Found {len(commits)} commits and {len(bugs_markdown)} bugs")
        
        # Generate analysis
        print("Generating analysis with Claude...")
        return self.claude_analyzer.analyze_release(version, bugs_markdown, commits)


def main():
    parser = argparse.ArgumentParser(
        description='Analyze a Firefox release using bmo-to-md for rich bug information',
        epilog='''Example: python firefox_analyzer.py 131.0
        
Environment variables:
  CLAUDE_API_KEY: Your Claude API key
  BMO_API_KEY: Your Bugzilla API key (used by bmo-to-md)
        '''
    )
    parser.add_argument('version', help='Firefox version to analyze (e.g., 131.0, 131)')
    parser.add_argument('--claude-key', help='Claude API key (or set CLAUDE_API_KEY env var)')
    parser.add_argument('--bmo-path', default='bmo-to-md',
                       help='Path to bmo-to-md executable (default: bmo-to-md)')
    parser.add_argument('--repo-path', default='.', 
                       help='Path to Firefox git repository (default: current directory)')
    parser.add_argument('--output', help='Output file path (default: print to stdout)')
    
    args = parser.parse_args()
    
    # Get Claude API key
    claude_api_key = args.claude_key or os.getenv('CLAUDE_API_KEY')
    
    if not claude_api_key:
        print("Error: Claude API key required. Use --claude-key or set CLAUDE_API_KEY environment variable")
        return 1
    
    # Check for BMO_API_KEY environment variable
    if not os.getenv('BMO_API_KEY'):
        print("Warning: BMO_API_KEY environment variable not set.")
        print("bmo-to-md will use anonymous access, which may have limitations.")
        print("Set BMO_API_KEY environment variable with your Bugzilla API key for best results.")
    else:
        print("Using BMO_API_KEY for authenticated Bugzilla access via bmo-to-md")
    
    try:
        # Initialize and run analyzer
        analyzer = FirefoxReleaseAnalyzer(claude_api_key, args.repo_path, args.bmo_path)
        result = analyzer.analyze_release(args.version)
        
        # Output result
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(result)
            print(f"Analysis saved to {args.output}")
        else:
            print("\n" + "="*80)
            print(f"FIREFOX {args.version} RELEASE ANALYSIS")
            print("="*80)
            print(result)
            
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
