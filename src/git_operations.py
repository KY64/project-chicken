import os
import subprocess
import sys
from typing import List, Literal


def configure_git() -> None:
    """Configure git with user name and email."""
    user_name = os.getenv('GIT_USER_NAME', 'github-actions[bot]')
    user_email = os.getenv('GIT_USER_EMAIL', '41898282+github-actions[bot]@users.noreply.github.com')

    subprocess.run(['git', 'config', 'user.name', user_name], check=True)
    subprocess.run(['git', 'config', 'user.email', user_email], check=True)


def get_app_env() -> Literal['develop', 'production']:
    """
    Read and validate APP_ENV.

    Must be explicitly set to 'develop' or 'production'.
    Exits with an error if unset or invalid.
    """
    env = os.getenv('APP_ENV')
    if env is None:
        sys.exit("Error: APP_ENV must be set to 'develop' or 'production'")
    if env not in ('develop', 'production'):
        sys.exit(f"Error: APP_ENV must be 'develop' or 'production', got {env!r}")
    return env


def pushes_enabled() -> bool:
    """Return True only when APP_ENV=production."""
    return get_app_env() == 'production'


def checkout_orphan_branch(branch_name: str) -> None:
    """
    Checkout an existing orphan branch or create a new one.

    Args:
        branch_name: Name of the orphan branch to checkout/create
    """
    # Check if branch exists locally
    local_check = subprocess.run(
        ['git', 'branch', '--list', branch_name],
        capture_output=True,
        text=True
    )

    if local_check.stdout.strip():
        # Branch exists locally, checkout it
        subprocess.run(['git', 'checkout', branch_name], check=True)
        subprocess.run(['git', 'reset', '--hard', 'HEAD'], check=True)
        return

    # The remote lookup is production-only: develop runs never touch the
    # network, so a missing local branch is created fresh as an orphan.
    if pushes_enabled():
        remote_check = subprocess.run(
            ['git', 'ls-remote', '--heads', 'origin', branch_name],
            capture_output=True,
            text=True
        )

        if remote_check.returncode == 0 and remote_check.stdout.strip():
            # Branch exists remotely, checkout and pull
            subprocess.run(['git', 'checkout', branch_name], check=True)
            subprocess.run(['git', 'pull', 'origin', branch_name], check=True)
            return

    # Branch doesn't exist (or develop mode), create orphan branch
    subprocess.run(['git', 'checkout', '--orphan', branch_name], check=True)
    # Clear the index to make it truly empty (may fail if index is already empty)
    subprocess.run(['git', 'rm', '-rf', '.'], check=False)


def push_branch(branch_name: str) -> None:
    """
    Push a branch to origin if remote exists and APP_ENV=production.

    Args:
        branch_name: Name of the branch to push
    """
    if not pushes_enabled():
        return

    # Check if origin exists
    remote_check = subprocess.run(
        ['git', 'remote', 'get-url', 'origin'],
        capture_output=True,
        text=True
    )

    if remote_check.returncode == 0:
        subprocess.run(['git', 'push', 'origin', branch_name, '--force'], check=True)


def checkout_main() -> None:
    """Checkout the main branch."""
    # Nothing is written while on orphan branches, so there are no untracked
    # files that could conflict with the switch. Do not re-add a git clean
    # here: it would delete unrelated untracked files such as .env
    subprocess.run(['git', 'checkout', 'main'], check=True)

    # Pull only in production. Develop runs never touch the network; a
    # failed pull here would crash the run before state files are saved,
    # losing the record of everything published in this run.
    if not pushes_enabled():
        return

    # Only pull if origin exists
    remote_check = subprocess.run(
        ['git', 'remote', 'get-url', 'origin'],
        capture_output=True,
        text=True
    )

    if remote_check.returncode == 0:
        subprocess.run(['git', 'pull', 'origin', 'main'], check=True)


def commit_changes(message: str, paths: List[str]) -> None:
    """
    Commit changes to the given files with the given message.

    Staging and committing are scoped to `paths` so unrelated working-tree
    files are never swept into the commit. Skips the commit when nothing
    changed, since committing with a clean index exits non-zero.

    Args:
        message: Commit message
        paths: Files to stage and commit
    """
    if not paths:
        print("No state changes to commit")
        return

    subprocess.run(['git', 'add', '--'] + paths, check=True)

    staged = subprocess.run(
        ['git', 'diff', '--cached', '--quiet', '--'] + paths,
        check=False
    )
    if staged.returncode == 0:
        print("No state changes to commit")
        return

    subprocess.run(['git', 'commit', '-m', message, '--'] + paths, check=True)


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
