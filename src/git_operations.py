import os
import subprocess
from typing import Optional


def configure_git() -> None:
    """Configure git with user name and email."""
    user_name = os.getenv('GIT_USER_NAME', 'github-actions[bot]')
    user_email = os.getenv('GIT_USER_EMAIL', '41898282+github-actions[bot]@users.noreply.github.com')
    
    subprocess.run(['git', 'config', 'user.name', user_name], check=True)
    subprocess.run(['git', 'config', 'user.email', user_email], check=True)


def checkout_orphan_branch(branch_name: str) -> None:
    """
    Checkout an existing orphan branch or create a new one.
    
    Args:
        branch_name: Name of the orphan branch to checkout/create
    """
    # Check if branch exists remotely
    result = subprocess.run(
        ['git', 'ls-remote', '--heads', 'origin', branch_name],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        # Branch exists, checkout it
        subprocess.run(['git', 'checkout', branch_name], check=True)
        subprocess.run(['git', 'pull', 'origin', branch_name], check=True)
    else:
        # Branch doesn't exist, create orphan branch
        subprocess.run(['git', 'checkout', '--orphan', branch_name], check=True)
        # Clear the index to make it truly empty (may fail if index is already empty)
        subprocess.run(['git', 'rm', '-rf', '.'], check=False)


def push_branch(branch_name: str) -> None:
    """
    Push a branch to origin.
    
    Args:
        branch_name: Name of the branch to push
    """
    subprocess.run(['git', 'push', 'origin', branch_name, '--force'], check=True)


def checkout_main() -> None:
    """Checkout the main branch."""
    subprocess.run(['git', 'checkout', 'main'], check=True)
    subprocess.run(['git', 'pull', 'origin', 'main'], check=True)


def commit_changes(message: str) -> None:
    """
    Commit current changes with the given message.
    
    Args:
        message: Commit message
    """
    subprocess.run(['git', 'add', '.'], check=True)
    subprocess.run(['git', 'commit', '-m', message], check=True)


def create_empty_commit(title: str, url: str) -> None:
    """
    Create an empty commit with title as header and URL as body.
    
    Args:
        title: Article title (commit header)
        url: Article URL (commit body)
    """
    subprocess.run(
        ['git', 'commit', '--allow-empty', '-m', title, '-m', url],
        check=True
    )
