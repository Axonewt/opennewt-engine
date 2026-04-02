"""
GitHub API 客户端封装

提供 GitHub 仓库操作的核心功能：
- Issue 管理
- Pull Request 管理
- 文件操作
- 仓库信息查询
"""

import os
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

from github import Github, Repository, Issue, PullRequest
from github.GithubException import GithubException

logger = logging.getLogger(__name__)


class GitHubClient:
    """GitHub API 客户端"""
    
    def __init__(
        self,
        token: Optional[str] = None,
        repo_name: str = "Axonewt/opennewt"
    ):
        """
        初始化 GitHub 客户端
        
        Args:
            token: GitHub Personal Access Token，如未提供则从 GITHUB_TOKEN 环境变量读取
            repo_name: 仓库名称，格式为 "owner/repo"
        """
        self.token = token or os.getenv("GITHUB_TOKEN")
        if not self.token:
            raise ValueError(
                "GitHub token 未提供。请设置 GITHUB_TOKEN 环境变量或在初始化时传入 token 参数。"
            )
        
        self.repo_name = repo_name
        self.client = Github(self.token)
        self._repo: Optional[Repository] = None
    
    @property
    def repo(self) -> Repository:
        """延迟加载仓库对象"""
        if self._repo is None:
            self._repo = self.client.get_repo(self.repo_name)
        return self._repo
    
    # ==================== Issue 管理 ====================
    
    def create_issue(
        self,
        title: str,
        body: Optional[str] = None,
        labels: Optional[List[str]] = None,
        assignees: Optional[List[str]] = None,
        milestone: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        创建 Issue
        
        Args:
            title: Issue 标题
            body: Issue 内容
            labels: 标签列表
            assignees: 指派人列表
            milestone: 里程碑标题
        
        Returns:
            创建的 Issue 信息字典
        """
        try:
            kwargs = {"title": title}
            if body:
                kwargs["body"] = body
            if labels:
                kwargs["labels"] = labels
            if assignees:
                kwargs["assignees"] = assignees
            if milestone:
                milestone_obj = self.repo.get_milestone(milestone)
                kwargs["milestone"] = milestone_obj
            
            issue = self.repo.create_issue(**kwargs)
            logger.info(f"创建 Issue #{issue.number}: {title}")
            
            return {
                "number": issue.number,
                "title": issue.title,
                "url": issue.html_url,
                "state": issue.state,
                "created_at": issue.created_at.isoformat()
            }
        except GithubException as e:
            logger.error(f"创建 Issue 失败: {e}")
            raise
    
    def get_issue(self, issue_number: int) -> Dict[str, Any]:
        """
        获取 Issue 详情
        
        Args:
            issue_number: Issue 编号
        
        Returns:
            Issue 信息字典
        """
        try:
            issue = self.repo.get_issue(issue_number)
            return {
                "number": issue.number,
                "title": issue.title,
                "body": issue.body,
                "state": issue.state,
                "labels": [label.name for label in issue.labels],
                "assignees": [a.login for a in issue.assignees],
                "created_at": issue.created_at.isoformat(),
                "updated_at": issue.updated_at.isoformat(),
                "url": issue.html_url
            }
        except GithubException as e:
            logger.error(f"获取 Issue #{issue_number} 失败: {e}")
            raise
    
    def update_issue(
        self,
        issue_number: int,
        title: Optional[str] = None,
        body: Optional[str] = None,
        labels: Optional[List[str]] = None,
        state: Optional[str] = None,
        assignees: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        更新 Issue
        
        Args:
            issue_number: Issue 编号
            title: 新标题
            body: 新内容
            labels: 新标签列表
            state: 新状态 ("open" 或 "closed")
            assignees: 新指派人列表
        
        Returns:
            更新后的 Issue 信息
        """
        try:
            issue = self.repo.get_issue(issue_number)
            
            kwargs = {}
            if title:
                kwargs["title"] = title
            if body:
                kwargs["body"] = body
            if labels:
                kwargs["labels"] = labels
            if state:
                kwargs["state"] = state
            if assignees:
                kwargs["assignees"] = assignees
            
            issue.edit(**kwargs)
            logger.info(f"更新 Issue #{issue_number}")
            
            return self.get_issue(issue_number)
        except GithubException as e:
            logger.error(f"更新 Issue #{issue_number} 失败: {e}")
            raise
    
    def create_comment(self, issue_number: int, body: str) -> Dict[str, Any]:
        """
        为 Issue 添加评论
        
        Args:
            issue_number: Issue 编号
            body: 评论内容
        
        Returns:
            评论信息
        """
        try:
            issue = self.repo.get_issue(issue_number)
            comment = issue.create_comment(body)
            logger.info(f"为 Issue #{issue_number} 添加评论")
            
            return {
                "id": comment.id,
                "body": comment.body,
                "user": comment.user.login,
                "created_at": comment.created_at.isoformat(),
                "url": comment.html_url
            }
        except GithubException as e:
            logger.error(f"添加评论失败: {e}")
            raise
    
    def add_issue_comment(self, issue_number: int, body: str) -> Dict[str, Any]:
        """
        为 Issue 添加评论（create_comment 的别名）
        
        Args:
            issue_number: Issue 编号
            body: 评论内容
        
        Returns:
            评论信息
        """
        return self.create_comment(issue_number, body)
    
    def get_issue_comments(self, issue_number: int) -> List[Dict[str, Any]]:
        """
        获取 Issue 的所有评论
        
        Args:
            issue_number: Issue 编号
        
        Returns:
            评论列表
        """
        try:
            issue = self.repo.get_issue(issue_number)
            comments = issue.get_comments()
            
            result = []
            for comment in comments:
                result.append({
                    "id": comment.id,
                    "body": comment.body,
                    "user": comment.user.login,
                    "created_at": comment.created_at.isoformat(),
                    "updated_at": comment.updated_at.isoformat() if hasattr(comment, 'updated_at') else comment.created_at.isoformat(),
                    "url": comment.html_url
                })
            
            return result
        except GithubException as e:
            logger.error(f"获取 Issue #{issue_number} 评论失败: {e}")
            raise
    
    def list_issues(
        self,
        state: str = "open",
        labels: Optional[List[str]] = None,
        assignee: Optional[str] = None,
        limit: int = 30
    ) -> List[Dict[str, Any]]:
        """
        列出 Issues
        
        Args:
            state: 状态过滤 ("open", "closed", "all")
            labels: 标签过滤
            assignee: 指派人过滤
            limit: 返回数量限制
        
        Returns:
            Issue 列表
        """
        try:
            kwargs = {"state": state}
            if labels:
                kwargs["labels"] = ",".join(labels)
            if assignee:
                kwargs["assignee"] = assignee
            
            issues = self.repo.get_issues(**kwargs)
            result = []
            for issue in issues[:limit]:
                result.append({
                    "number": issue.number,
                    "title": issue.title,
                    "state": issue.state,
                    "labels": [l.name for l in issue.labels],
                    "url": issue.html_url
                })
            return result
        except GithubException as e:
            logger.error(f"列出 Issues 失败: {e}")
            raise
    
    # ==================== Pull Request 管理 ====================
    
    def create_pr(
        self,
        title: str,
        body: Optional[str],
        head: str,
        base: str = "main",
        draft: bool = False,
        labels: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        创建 Pull Request
        
        Args:
            title: PR 标题
            body: PR 描述
            head: 源分支名
            base: 目标分支名
            draft: 是否为草稿 PR
            labels: 标签列表
        
        Returns:
            PR 信息
        """
        try:
            pr = self.repo.create_pull(
                title=title,
                body=body or "",
                head=head,
                base=base,
                draft=draft
            )
            
            # 添加标签
            if labels:
                pr.add_to_labels(*labels)
            
            logger.info(f"创建 PR #{pr.number}: {title}")
            
            return {
                "number": pr.number,
                "title": pr.title,
                "url": pr.html_url,
                "state": pr.state,
                "head": pr.head.ref,
                "base": pr.base.ref,
                "draft": pr.draft,
                "created_at": pr.created_at.isoformat()
            }
        except GithubException as e:
            logger.error(f"创建 PR 失败: {e}")
            raise
    
    def get_pr(self, pr_number: int) -> Dict[str, Any]:
        """
        获取 PR 详情
        
        Args:
            pr_number: PR 编号
        
        Returns:
            PR 信息
        """
        try:
            pr = self.repo.get_pull(pr_number)
            return {
                "number": pr.number,
                "title": pr.title,
                "body": pr.body,
                "state": pr.state,
                "head": pr.head.ref,
                "base": pr.base.ref,
                "merged": pr.merged,
                "draft": pr.draft,
                "mergeable": pr.mergeable,
                "url": pr.html_url
            }
        except GithubException as e:
            logger.error(f"获取 PR #{pr_number} 失败: {e}")
            raise
    
    # ==================== 文件操作 ====================
    
    def get_file_content(
        self,
        path: str,
        ref: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        获取文件内容
        
        Args:
            path: 文件路径
            ref: 分支/提交引用
        
        Returns:
            文件信息（包含内容）
        """
        try:
            kwargs = {"path": path}
            if ref:
                kwargs["ref"] = ref
            
            content_file = self.repo.get_contents(**kwargs)
            
            if isinstance(content_file, list):
                # 目录，返回文件列表
                return {
                    "type": "dir",
                    "files": [
                        {"name": f.name, "path": f.path, "type": f.type}
                        for f in content_file
                    ]
                }
            
            return {
                "type": "file",
                "name": content_file.name,
                "path": content_file.path,
                "content": content_file.decoded_content.decode("utf-8"),
                "sha": content_file.sha,
                "size": content_file.size
            }
        except GithubException as e:
            logger.error(f"获取文件 {path} 失败: {e}")
            raise
    
    def update_file(
        self,
        path: str,
        content: str,
        message: str,
        branch: Optional[str] = None,
        sha: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        更新文件内容
        
        Args:
            path: 文件路径
            content: 新内容
            message: 提交消息
            branch: 目标分支
            sha: 文件 SHA（如果已知可提供，否则自动获取）
        
        Returns:
            更新结果
        """
        try:
            # 获取当前文件的 SHA
            if not sha:
                current = self.repo.get_contents(path, ref=branch)
                sha = current.sha
            
            kwargs = {
                "path": path,
                "message": message,
                "content": content,
                "sha": sha
            }
            if branch:
                kwargs["branch"] = branch
            
            result = self.repo.update_file(**kwargs)
            logger.info(f"更新文件 {path}")
            
            return {
                "commit": result["commit"].sha,
                "url": f"https://github.com/{self.repo_name}/commit/{result['commit'].sha}"
            }
        except GithubException as e:
            logger.error(f"更新文件 {path} 失败: {e}")
            raise
    
    def create_file(
        self,
        path: str,
        content: str,
        message: str,
        branch: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        创建新文件
        
        Args:
            path: 文件路径
            content: 文件内容
            message: 提交消息
            branch: 目标分支
        
        Returns:
            创建结果
        """
        try:
            kwargs = {
                "path": path,
                "message": message,
                "content": content
            }
            if branch:
                kwargs["branch"] = branch
            
            result = self.repo.create_file(**kwargs)
            logger.info(f"创建文件 {path}")
            
            return {
                "commit": result["commit"].sha,
                "url": f"https://github.com/{self.repo_name}/blob/main/{path}"
            }
        except GithubException as e:
            logger.error(f"创建文件 {path} 失败: {e}")
            raise
    
    # ==================== 分支操作 ====================
    
    def create_branch(
        self,
        branch_name: str,
        base_branch: str = "main"
    ) -> Dict[str, Any]:
        """
        创建分支
        
        Args:
            branch_name: 新分支名
            base_branch: 基础分支
        
        Returns:
            创建结果
        """
        try:
            ref = self.repo.get_git_ref(f"heads/{base_branch}")
            new_ref = self.repo.create_git_ref(
                ref=f"refs/heads/{branch_name}",
                sha=ref.object.sha
            )
            logger.info(f"创建分支 {branch_name} 基于 {base_branch}")
            
            return {
                "branch": branch_name,
                "sha": new_ref.object.sha,
                "url": f"https://github.com/{self.repo_name}/tree/{branch_name}"
            }
        except GithubException as e:
            logger.error(f"创建分支 {branch_name} 失败: {e}")
            raise
    
    def list_branches(self) -> List[Dict[str, Any]]:
        """列出所有分支"""
        try:
            branches = self.repo.get_branches()
            return [
                {
                    "name": b.name,
                    "sha": b.commit.sha,
                    "protected": b.protected
                }
                for b in branches
            ]
        except GithubException as e:
            logger.error(f"列出分支失败: {e}")
            raise
    
    # ==================== 仓库信息 ====================
    
    def get_repo_info(self) -> Dict[str, Any]:
        """获取仓库信息"""
        try:
            return {
                "name": self.repo.name,
                "full_name": self.repo.full_name,
                "description": self.repo.description,
                "url": self.repo.html_url,
                "stars": self.repo.stargazers_count,
                "forks": self.repo.forks_count,
                "open_issues": self.repo.open_issues_count,
                "default_branch": self.repo.default_branch,
                "language": self.repo.language,
                "created_at": self.repo.created_at.isoformat(),
                "updated_at": self.repo.updated_at.isoformat()
            }
        except GithubException as e:
            logger.error(f"获取仓库信息失败: {e}")
            raise
    
    def test_connection(self) -> Dict[str, Any]:
        """
        测试 GitHub 连接
        
        Returns:
            连接状态信息
        """
        try:
            user = self.client.get_user()
            rate_limit = self.client.get_rate_limit()
            
            return {
                "status": "success",
                "authenticated_user": user.login,
                "repo": self.repo_name,
                "rate_limit": {
                    "remaining": rate_limit.core.remaining,
                    "limit": rate_limit.core.limit,
                    "reset_time": rate_limit.core.reset.isoformat()
                }
            }
        except GithubException as e:
            return {
                "status": "failed",
                "error": str(e)
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": f"连接失败: {str(e)}"
            }
    
    # ==================== 仓库检查与创建 ====================
    
    def check_repo_exists(self) -> Dict[str, Any]:
        """
        检查目标仓库是否存在
        
        Returns:
            包含 exists 状态和详细信息的字典
        """
        try:
            repo = self.client.get_repo(self.repo_name)
            return {
                "exists": True,
                "name": repo.name,
                "full_name": repo.full_name,
                "description": repo.description,
                "url": repo.html_url,
                "private": repo.private,
                "default_branch": repo.default_branch
            }
        except GithubException as e:
            if e.status == 404:
                return {
                    "exists": False,
                    "error": "仓库不存在",
                    "repo_name": self.repo_name
                }
            else:
                return {
                    "exists": False,
                    "error": str(e),
                    "repo_name": self.repo_name
                }
        except Exception as e:
            return {
                "exists": False,
                "error": f"检查失败: {str(e)}",
                "repo_name": self.repo_name
            }
    
    def create_repo(
        self,
        org: Optional[str] = None,
        description: str = "",
        private: bool = False,
        auto_init: bool = True,
        gitignore_template: Optional[str] = "Python"
    ) -> Dict[str, Any]:
        """
        创建 GitHub 仓库
        
        注意：此方法需要有相应权限的 token
        
        Args:
            org: 组织名（如创建组织仓库），None 则创建个人仓库
            description: 仓库描述
            private: 是否私有
            auto_init: 是否自动初始化（添加 README）
            gitignore_template: gitignore 模板
        
        Returns:
            创建的仓库信息
        """
        try:
            # 解析仓库名
            parts = self.repo_name.split("/")
            if len(parts) != 2:
                raise ValueError(f"无效的仓库名格式: {self.repo_name}，应为 'owner/repo'")
            
            owner, repo_name = parts
            
            kwargs = {
                "name": repo_name,
                "description": description,
                "private": private,
                "auto_init": auto_init,
            }
            
            if gitignore_template:
                kwargs["gitignore_template"] = gitignore_template
            
            if org:
                # 创建组织仓库
                organization = self.client.get_organization(org)
                repo = organization.create_repo(**kwargs)
            else:
                # 创建个人仓库
                repo = self.client.get_user().create_repo(**kwargs)
            
            logger.info(f"创建仓库: {repo.full_name}")
            
            # 刷新缓存的仓库对象
            self._repo = repo
            
            return {
                "success": True,
                "name": repo.name,
                "full_name": repo.full_name,
                "url": repo.html_url,
                "clone_url": repo.clone_url,
                "default_branch": repo.default_branch
            }
        except GithubException as e:
            logger.error(f"创建仓库失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "repo_name": self.repo_name
            }
        except Exception as e:
            logger.error(f"创建仓库异常: {e}")
            return {
                "success": False,
                "error": str(e),
                "repo_name": self.repo_name
            }
    
    def get_repo_creation_guide(self) -> str:
        """
        获取仓库创建指南
        
        Returns:
            创建指南文本
        """
        guide = f"""
# 创建 GitHub 仓库指南

目标仓库: {self.repo_name}

## 方法 1: 通过 GitHub Web 界面创建（推荐）

### 步骤：
1. 访问 https://github.com/new
2. 填写仓库信息：
   - Repository name: {self.repo_name.split('/')[-1]}
   - Description: OpenNewt - Axonewt Neural Plasticity Engine
   - 选择 Public 或 Private
   - ✅ Add a README file
   - ✅ Add .gitignore (选择 Python 模板)
   - License: MIT 或 Apache 2.0
3. 点击 "Create repository"

### 如果需要在组织中创建：
- 访问 https://github.com/organizations/{self.repo_name.split('/')[0]}/repositories/new
- 或在组织页面中点击 "New repository"

## 方法 2: 通过 API 创建（需要权限）

使用本客户端创建：

```python
from integrations.github_client import create_github_client

client = create_github_client()

# 检查仓库是否存在
result = client.check_repo_exists()
if not result['exists']:
    # 创建仓库
    create_result = client.create_repo(
        description="OpenNewt - Axonewt Neural Plasticity Engine",
        private=False,
        auto_init=True,
        gitignore_template="Python"
    )
    print(f"创建结果: {{create_result}}")
```

## 方法 3: 本地 Git 推送创建

1. 初始化本地仓库：
   ```bash
   cd D:/opennewt
   git init
   git add .
   git commit -m "Initial commit"
   ```

2. 在 GitHub 创建空仓库（不要勾选 README）

3. 添加远程仓库并推送：
   ```bash
   git remote add origin https://github.com/{self.repo_name}.git
   git branch -M main
   git push -u origin main
   ```

## 所需 Token 权限

创建仓库需要以下权限：
- `repo` - 完整仓库访问
- `public_repo` - 创建公共仓库（如果只创建公共仓库）
- `repo:status`
- `repo_deployment`
- `read:repo_hook`
- `write:repo_hook`

如果创建组织仓库，还需要：
- 组织的 Admin 权限

## 验证仓库状态

```python
client = create_github_client()
result = client.check_repo_exists()
print(result)
```
"""
        return guide


# ==================== 便捷函数 ====================

def create_github_client(
    repo_name: str = "Axonewt/opennewt",
    token: Optional[str] = None
) -> GitHubClient:
    """
    创建 GitHub 客户端的便捷函数
    
    Args:
        repo_name: 仓库名称
        token: GitHub token
    
    Returns:
        GitHubClient 实例
    """
    return GitHubClient(token=token, repo_name=repo_name)
